"""Bounded Development-only play/game validation and deterministic population summaries.

Target scores enter evaluation only, never ``simulate_play_game``. The historical
fixture uses one model frozen through 2023, including its team priors, throughout
the first 32 regular-season 2024 games. This is retrospective research validation,
not a claim that the archive was physically registered before those games.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

import numpy as np

from .labs_simulation import summarize_scores


SCRIMMAGE = {"RUSH", "QB_SNEAK", "QB_SCRAMBLE", "PASS_COMPLETE", "PASS_INCOMPLETE", "SACK", "INTERCEPTION", "KNEEL", "SPIKE"}
PASS_ATTEMPTS = {"PASS_COMPLETE", "PASS_INCOMPLETE", "INTERCEPTION", "SPIKE"}
DROPBACKS = PASS_ATTEMPTS | {"SACK", "QB_SCRAMBLE"}


def pmf(values: np.ndarray, field_name: str) -> list[dict[str, Any]]:
    values, counts = np.unique(values, return_counts=True)
    return [{field_name: int(value), "probability": float(count / counts.sum())}
            for value, count in zip(values, counts, strict=True)]


def distribution_summary(finals: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not finals:
        raise ValueError("empty simulated population")
    home = np.asarray([g["homeScore"] for g in finals], dtype=np.int64)
    away = np.asarray([g["awayScore"] for g in finals], dtype=np.int64)
    pairs, counts = np.unique(np.column_stack((home, away)), axis=0, return_counts=True)
    return {
        "drawCount": len(finals), "scoreSummary": summarize_scores(home, away),
        "jointScoreDistribution": [{"homeScore": int(pair[0]), "awayScore": int(pair[1]), "probability": float(count / len(finals))}
                                   for pair, count in zip(pairs, counts, strict=True)],
        "scoreMarginDistribution": pmf(home - away, "homeMinusAway"),
        "totalScoreDistribution": pmf(home + away, "totalScore"),
        "quantiles": {name: {str(q): float(np.quantile(values, q)) for q in (.05, .25, .5, .75, .95)}
                      for name, values in (("homeScore", home), ("awayScore", away), ("marginHomeMinusAway", home-away), ("total", home+away))},
        "reachingOvertimeProbability": float(np.mean([bool(g.get("reachedOvertime")) for g in finals])),
        "finalTieProbability": float(np.mean(home == away)),
    }


def representative_indices(finals: list[Mapping[str, Any]]) -> dict[str, int]:
    """Six distinct existing simulations. Missing classes are explicit, never relabeled."""
    home = np.asarray([g["homeScore"] for g in finals]); away = np.asarray([g["awayScore"] for g in finals])
    total, margin = home+away, home-away
    order = np.arange(len(finals))
    choices = [
        ("Typical", np.lexsort((order, np.abs(total-np.median(total)) + np.abs(margin-np.median(margin))))),
        ("Close", np.lexsort((order, np.abs(total-np.median(total)), np.abs(margin)))),
        ("Home win", order[margin > 0]), ("Away win", order[margin < 0]),
        ("High scoring", np.lexsort((order, -total))), ("Low scoring", np.lexsort((order, total))),
    ]
    selected: dict[str, int] = {}; used: set[int] = set()
    for label, candidates in choices:
        candidate = next((int(i) for i in candidates if int(i) not in used), None)
        if candidate is None:
            raise ValueError(f"representative class unavailable without fabrication: {label}")
        selected[label] = candidate; used.add(candidate)
    return selected


@dataclass
class PopulationAccounting:
    """Accumulate all simulated plays before discarding non-representative paths."""
    games: int = 0
    counts: Counter = field(default_factory=Counter)
    yards: list[float] = field(default_factory=list)
    seconds: list[float] = field(default_factory=list)
    play_counts: list[int] = field(default_factory=list)
    drive_counts: list[int] = field(default_factory=list)
    score_mismatch: int = 0
    continuity_mismatch: int = 0
    state_domain_violations: int = 0

    def add(self, game: Mapping[str, Any]) -> None:
        plays = game["plays"]
        self.games += 1
        self.play_counts.append(sum(p["playType"] != "PERIOD_END" for p in plays))
        drives = {p["driveNumber"] for p in plays if p["stateBefore"]["phase"] == "SCRIMMAGE"}
        self.drive_counts.append(len(drives))
        home = away = 0
        previous = None
        for play in plays:
            kind = play["playType"]; before = play["stateBefore"]; after = play["stateAfter"]; outcome = play["outcome"]
            self.counts[kind] += 1
            if previous is not None and previous != before:
                self.continuity_mismatch += 1
            previous = after
            dh, da = int(outcome.get("homePointsAdded", 0)), int(outcome.get("awayPointsAdded", 0))
            home += dh; away += da
            if int(after["homeScore"])-int(before["homeScore"]) != dh or int(after["awayScore"])-int(before["awayScore"]) != da:
                self.score_mismatch += 1
            for state in (before, after):
                if (state["possession"] not in ("HOME", "AWAY") or not 1 <= state["quarter"] <= 5
                        or not 0 <= state["down"] <= 4 or not 0 <= state["distance"] <= 100
                        or not 0 <= state["yardline100"] <= 100 or state["clockSeconds"] < 0
                        or state["gameSecondsRemaining"] < 0 or state["homeScore"] < 0 or state["awayScore"] < 0):
                    self.state_domain_violations += 1
            if kind != "PERIOD_END":
                self.seconds.append(float(outcome.get("seconds", 0)))
            self.counts["TURNOVER_EVENTS"] += bool(outcome.get("turnover"))
            self.counts["FUMBLES"] += bool(outcome.get("fumble"))
            self.counts["FUMBLES_LOST"] += bool(outcome.get("fumbleLost"))
            self.counts["TURNOVER_DOWNS"] += bool(outcome.get("turnoverDowns"))
            self.counts["POINTS"] += dh + da
            if kind in SCRIMMAGE:
                self.counts["SCRIMMAGE_PLAYS"] += 1
                # Endpoints may identify an interception/recovery location; they
                # are not net offensive yards. The engine states net yards.
                if outcome.get("yardsGained") is not None:
                    self.yards.append(float(outcome["yardsGained"]))
                converted = bool(outcome.get("firstDown")) and not bool(outcome.get("turnover"))
                self.counts["FIRST_DOWN_OR_TD"] += converted
                if before["down"] in (3, 4):
                    self.counts[f"DOWN_{before['down']}_ATTEMPTS"] += 1
                    self.counts[f"DOWN_{before['down']}_CONVERTED"] += converted
        if home != game["homeScore"] or away != game["awayScore"]:
            self.score_mismatch += 1

    def result(self) -> dict[str, Any]:
        n = self.counts
        attempts = sum(n[p] for p in PASS_ATTEMPTS); dropbacks = sum(n[p] for p in DROPBACKS)
        plays = sum(self.play_counts); drives = sum(self.drive_counts)
        def divide(a: float, b: float) -> float | None:
            return float(a / b) if b else None
        def moments(values: Iterable[float]) -> dict[str, Any]:
            array = np.asarray(list(values), dtype=float)
            return {"count": len(array), "mean": float(array.mean()) if len(array) else None,
                    "standardDeviation": float(array.std()) if len(array) else None,
                    "quantiles": {str(q): float(np.quantile(array, q)) for q in (.05, .25, .5, .75, .95)} if len(array) else {}}
        return {
            "games": self.games, "plays": plays, "drives": drives,
            "playTypeCounts": {key: n[key] for key in sorted(n) if key not in {"POINTS", "SCRIMMAGE_PLAYS", "TURNOVER_EVENTS", "FUMBLES", "FUMBLES_LOST", "TURNOVER_DOWNS", "FIRST_DOWN_OR_TD"} and not key.startswith("DOWN_")},
            "completionRate": divide(n["PASS_COMPLETE"], attempts), "completionDenominator": attempts,
            "sackRatePerDropback": divide(n["SACK"], dropbacks), "dropbackDenominator": dropbacks,
            "turnoversPerGame": divide(n["INTERCEPTION"] + n["FUMBLES_LOST"], self.games),
            "fumblesPerGame": divide(n["FUMBLES"], self.games), "turnoverOnDownsPerGame": divide(n["TURNOVER_DOWNS"], self.games),
            "firstDownOrTouchdownRate": divide(n["FIRST_DOWN_OR_TD"], n["SCRIMMAGE_PLAYS"]),
            "scrimmageDenominator": n["SCRIMMAGE_PLAYS"],
            "thirdDownConversionRate": divide(n["DOWN_3_CONVERTED"], n["DOWN_3_ATTEMPTS"]), "thirdDownAttempts": n["DOWN_3_ATTEMPTS"],
            "fourthDownConversionRate": divide(n["DOWN_4_CONVERTED"], n["DOWN_4_ATTEMPTS"]), "fourthDownAttempts": n["DOWN_4_ATTEMPTS"],
            "pointsPerDrive": divide(n["POINTS"], drives),
            "yardsPerScrimmagePlay": moments(self.yards), "clockSecondsPerRecordedPlay": moments(self.seconds),
            "playsPerGame": moments(self.play_counts), "drivesPerGame": moments(self.drive_counts),
            "scoreReconciliationFailures": self.score_mismatch,
            "stateContinuityFailures": self.continuity_mismatch, "stateDomainViolations": self.state_domain_violations,
            "impossibleStateCount": self.score_mismatch + self.continuity_mismatch + self.state_domain_violations,
            "denominatorNotes": "Scrimmage excludes kicks/tries/penalties/period markers. Dropback includes sacks/scrambles; attempts exclude both. First down/TD uses the engine's explicit conversion flag and excludes turnovers. Net offensive yards exclude throw/recovery/return locations. Points/drive includes all scoreboard points (including defensive scores). Clock is supplied sampled consumption, not tracking time.",
        }


def historical_game_validation(model: Any, schedule: list[Mapping[str, Any]], *, simulate: Callable[..., dict[str, Any]],
                               draws: int = 200, maximum_games: int = 32, seed: int = 930947) -> dict[str, Any]:
    chosen = sorted((g for g in schedule if int(g["season"]) == 2024 and g["seasonType"] == "REG"), key=lambda g: (g["date"], g["gameId"]))[:maximum_games]
    if len(chosen) != maximum_games:
        raise ValueError("historical fixture lacks declared 32 regular-season 2024 games")
    accounting = PopulationAccounting(); rows = []
    for game_index, actual in enumerate(chosen):
        finals = []
        for index in range(draws):
            generated = simulate(model, home_team=actual["homeTeam"], away_team=actual["awayTeam"], season=2024,
                                 seed=seed + game_index * 100_000 + index, scenario="BASE", postseason=False, include_geometry=False)
            accounting.add(generated)
            finals.append({"homeScore": generated["homeScore"], "awayScore": generated["awayScore"], "reachedOvertime": generated["reachedOvertime"]})
        summary = distribution_summary(finals)
        observed = int(actual["homeScore"]) - int(actual["awayScore"])
        outcome = 0 if observed > 0 else 1 if observed < 0 else 2
        s = summary["scoreSummary"]
        probabilities = np.asarray([s["homeWinProbability"], s["awayWinProbability"], s["tieProbability"]])
        truth = np.eye(3)[outcome]
        rows.append({"gameId": actual["gameId"], "date": actual["date"], "homeTeam": actual["homeTeam"], "awayTeam": actual["awayTeam"],
                     "actualHomeScore": int(actual["homeScore"]), "actualAwayScore": int(actual["awayScore"]),
                     "simulated": s, "jointScoreDistribution": summary["jointScoreDistribution"],
                     "logLoss": float(-np.log(max(float(probabilities[outcome]), 1e-15))),
                     "multiclassBrierSum": float(np.sum((probabilities-truth)**2)),
                     "zeroDrawProbabilityOfObservedClass": bool(probabilities[outcome] == 0),
                     "marginAbsoluteError": abs(s["expectedMarginHomeMinusAway"] - observed),
                     "totalAbsoluteError": abs(s["expectedTotal"]-int(actual["homeScore"])-int(actual["awayScore"])),
                     "homeScoreAbsoluteError": abs(s["expectedHomeScore"]-int(actual["homeScore"])),
                     "awayScoreAbsoluteError": abs(s["expectedAwayScore"]-int(actual["awayScore"]))})
        print(f"historical play fixture {game_index+1}/{maximum_games} {actual['gameId']} {draws} draws", flush=True)
    measures = ("logLoss", "multiclassBrierSum", "marginAbsoluteError", "totalAbsoluteError", "homeScoreAbsoluteError", "awayScoreAbsoluteError")
    return {"schemaVersion": "NFL_PLAY_LEVEL_HISTORICAL_GAME_VALIDATION_V1", "selection": "FIRST32_REGULAR_SEASON2024_GAMES_BY_DATE_THEN_GAME_ID_NO_OUTCOME_SELECTION",
            "trainingSeasons": list(range(2018, 2024)), "validationSeason": 2024,
            "games": len(rows), "drawsPerGame": draws, "seed": seed,
            "metrics": {key: float(np.mean([r[key] for r in rows])) for key in measures},
            "observedScoreSummary": {"expectedHomeScore": float(np.mean([r["actualHomeScore"] for r in rows])),
                                     "expectedAwayScore": float(np.mean([r["actualAwayScore"] for r in rows])),
                                     "expectedTotal": float(np.mean([r["actualHomeScore"]+r["actualAwayScore"] for r in rows])),
                                     "homeWinFrequency": float(np.mean([r["actualHomeScore"] > r["actualAwayScore"] for r in rows])),
                                     "awayWinFrequency": float(np.mean([r["actualHomeScore"] < r["actualAwayScore"] for r in rows])),
                                     "tieFrequency": float(np.mean([r["actualHomeScore"] == r["actualAwayScore"] for r in rows]))},
            "simulatedScoreSummary": {key: float(np.mean([r["simulated"][key] for r in rows])) for key in rows[0]["simulated"]},
            "observedDrivesPerGame": float(np.mean([g["observedDriveCount"] for g in chosen])) if all("observedDriveCount" in g for g in chosen) else None,
            "observedPointsPerDrive": float(sum(g["homeScore"]+g["awayScore"] for g in chosen) / sum(g["observedDriveCount"] for g in chosen)) if all(g.get("observedDriveCount", 0) > 0 for g in chosen) else None,
            "zeroDrawObservedClassGames": sum(r["zeroDrawProbabilityOfObservedClass"] for r in rows),
            "logLossNumericalFloor": 1e-15, "populationAccounting": accounting.result(), "perGame": rows,
            "pregameAuthority": "Only home/away identity, season and frozen through2023 model/prior state enter simulation. Validation outcomes are read solely for metric computation; no target-game state initializes games.",
            "limitations": ["Small first-two-week Development fixture, not full-season prospective calibration or wagering evidence.",
                            "Frozen2023 priors are not updated from2024 outcomes during this fixture.",
                            "Empirical finite-draw zero probabilities are reported explicitly and only clipped numerically for log loss; no calibration fit.",
                            "Historical nflverse archives were retrieved later; this is chronological retrospective validation, not proof of archived pre-kickoff releases."]}
