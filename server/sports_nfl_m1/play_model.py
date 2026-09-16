"""Independent hierarchical empirical NFL play model; research shadow only.

All outcome dimensions are sampled from ONE observed donor, not independent
yardage/clock/turnover draws. Fixed shrinkage weights are declared, not optimized
against validation. Unknown teams receive the empirical league prior, never a
generic median. No quarterback, weather, injury, market or target labels enter
the input context.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .play_evidence import PLAY_TYPES

PLAY_ENGINE = "NFL_DEVELOPMENT_HIERARCHICAL_PLAY_V1"
MODEL_CONFIG = {"offseasonRetention": .65, "downDistancePriorPlays": 300,
                "fieldPriorPlays": 120, "clockScorePriorPlays": 80,
                "teamUnitPriorPlays": 400, "teamUnitMixtureCoefficient": .5,
                "distanceBins": [2, 5, 10], "fieldBinWidth": 10,
                "lateHalfSeconds": 120, "clockMaxObservedSeconds": 120,
                "covariates": ["phase", "down", "yards_to_go", "yardline_100", "half_seconds",
                               "score_differential", "offense_team", "defense_team", "season"],
                "tryChoiceFieldTreatment": "EXCLUDED_ACTION_DEPENDENT_YARDLINE",
                "fitMethod": "recency-weighted joint empirical donors with nested hierarchical shrinkage",
                "teamTreatment": "separate previous-evidence offense/defense donor mixtures, exposure regressed to league and discounted across missing seasons"}
SCENARIOS = {
    "BASE": {"parameter": "none", "multiplier": 1.0},
    "FASTER_PACE": {"parameter": "observed_clock_seconds", "multiplier": .9},
    "SLOWER_PACE": {"parameter": "observed_clock_seconds", "multiplier": 1.1},
    "PASS_HEAVY": {"parameter": "pass_intent_odds_relative_to_other_intents", "multiplier": 1.25},
    "RUN_HEAVY": {"parameter": "pass_intent_odds_relative_to_other_intents", "multiplier": .8},
    "AGGRESSIVE_FOURTH": {"parameter": "fourth_down_go_odds_relative_to_kick_choices", "multiplier": 1.5},
    "ELEVATED_TURNOVER": {"parameter": "turnover_donor_odds", "multiplier": 1.25,
                           "limitation": "Elevated turnover risk sensitivity, not a variance-only intervention or causal/coaching prediction."},
}
PASS_INTENT = {"PASS_COMPLETE", "PASS_INCOMPLETE", "INTERCEPTION", "SACK", "QB_SCRAMBLE"}
GO_INTENT = PASS_INTENT | {"RUSH", "QB_SNEAK"}
OUTCOME_FIELDS = ("type", "yards", "seconds", "air_yards", "return_yards", "kick_distance", "touchback",
                  "fumble", "fumble_lost", "turnover", "touchdown", "safety", "first_down", "kick_success",
                  "ball_end_yardline_100", "turnover_yardline_100", "return_end_yardline_100",
                  "receiving_start_yardline_100", "location_evidence_status", "penalty_accepted", "penalty_yards",
                  "penalty_offense", "penalty_no_play", "penalty_automatic_first_down")


def _finite(value: Any, default: float) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (ValueError, TypeError):
        return default


def _required_number(state: dict[str, Any], key: str) -> float:
    if key not in state or state[key] is None:
        raise ValueError(f"missing required pre-play state: {key}")
    value = _finite(state[key], float("nan"))
    if not math.isfinite(value):
        raise ValueError(f"nonfinite required pre-play state: {key}")
    return value


def _context(state: dict[str, Any]) -> tuple[Any, ...]:
    phase = state.get("phase")
    if phase not in ("SCRIMMAGE", "TRY", "KICKOFF"):
        raise ValueError("unknown play phase")
    half = _required_number(state, "half_seconds")
    late = 2 if half <= 30 else (1 if half <= 120 else 0)
    score = _required_number(state, "score_differential")
    score_bin = int(np.searchsorted([-16, -8, -3, 0, 3, 8, 16], score, side="right")) if late else int(np.sign(score))
    if phase != "SCRIMMAGE":
        # TRY yardline is determined BY XP/two-point choice: do not leak it into
        # intent selection. Kickoff context excludes receiving/kicking ambiguity.
        return phase, 0, 0, 0, late, score_bin
    down_value = _required_number(state, "down")
    down = int(down_value)
    if down != down_value or down not in (1, 2, 3, 4):
        raise ValueError("scrimmage down must be 1--4")
    distance = int(np.searchsorted([2, 5, 10], _required_number(state, "yards_to_go"), side="left"))
    yard = _required_number(state, "yardline_100")
    if not 0 <= yard <= 100:
        raise ValueError("yardline must be in [0,100]")
    return phase, down, distance, min(9, int(yard // 10)), late, score_bin


@dataclass
class DonorGroup:
    indices: np.ndarray
    weights: np.ndarray
    cumulative: np.ndarray
    mass: float


@dataclass
class DonorBank:
    groups: dict[tuple[str, bool], DonorGroup]
    mass: float
    count: int


def _make_bank(indices: np.ndarray, rows: list[dict[str, Any]], weights: np.ndarray) -> DonorBank:
    groups: dict[tuple[str, bool], list[int]] = {}
    for index in indices:
        row = rows[int(index)]
        groups.setdefault((row["type"], bool(row["turnover"])), []).append(int(index))
    result = {}
    for key, ids in groups.items():
        selected = np.asarray(ids, dtype=np.int32)
        w = weights[selected]
        result[key] = DonorGroup(selected, w, np.cumsum(w), float(w.sum()))
    return DonorBank(result, sum(group.mass for group in result.values()), len(indices))


@dataclass
class PlayModel:
    rows: list[dict[str, Any]]
    banks: dict[tuple[Any, ...], DonorBank]
    training_cutoff: str
    training_season: int
    training_plays: int
    training_games: int
    cutoff_date_exclusive: str
    maximum_observed_field_goal_distance: float = 0.
    config: dict[str, Any] = field(default_factory=lambda: dict(MODEL_CONFIG))
    _cache: dict[tuple[Any, ...], tuple[list[tuple[DonorGroup, str]], np.ndarray, dict[str, float]]] = field(default_factory=dict, repr=False)
    _support_cache: dict[tuple[int, float], DonorGroup | None] = field(default_factory=dict, repr=False)
    exposure: Counter = field(default_factory=Counter)

    def __getstate__(self) -> dict[str, Any]:
        result = dict(self.__dict__)
        result["_cache"] = {}
        result["_support_cache"] = {}
        result["exposure"] = Counter()
        return result

    def current_team_state(self, home: str, away: str, season: int) -> dict[str, Any]:
        discount = .65 ** max(0, int(season) - self.training_season)
        return {"trainingSeason": self.training_season, "targetSeason": int(season),
                "missingSeasonDiscount": discount,
                "teams": {team: {unit: self.banks.get((unit, team, "SCRIMMAGE"), DonorBank({}, 0, 0)).mass * discount
                                 for unit in ("offense", "defense")} for team in (home, away)}}

    def _mixture(self, state: dict[str, Any]) -> list[tuple[DonorBank, float]]:
        phase, down, distance, field_bin, late, score = _context(state)
        base_key = ("phase", phase)
        if base_key not in self.banks:
            raise ValueError(f"no observed donor support for phase {phase}")
        mixture = [(self.banks[base_key], 1.0)]
        levels = [(("situation", phase, down, distance), 300),
                  (("field", phase, down, distance, field_bin), 120),
                  (("clock", phase, down, distance, field_bin, late, score), 80)]
        for key, strength in levels:
            bank = self.banks.get(key)
            if bank is None:
                continue
            weight = bank.mass / (bank.mass + strength)
            mixture = [(item, mass * (1 - weight)) for item, mass in mixture] + [(bank, weight)]
        season = int(state.get("season", self.training_season + 1))
        discount = .65 ** max(0, season - self.training_season)
        for unit, team in (("offense", state.get("offense_team")), ("defense", state.get("defense_team"))):
            bank = self.banks.get((unit, team, phase, down, distance, field_bin))
            if bank is None:
                bank = self.banks.get((unit, team, phase))
            if bank is not None:
                n = bank.mass * discount
                mixture.append((bank, .5 * n / (n + 400)))
        total = sum(weight for _, weight in mixture)
        return [(bank, weight / total) for bank, weight in mixture]

    def _supported_group(self, group: DonorGroup, kind: str, yard: float) -> DonorGroup | None:
        if kind not in ("INTERCEPTION", "KICKOFF", "PUNT") and not self.rows[int(group.indices[0])]["turnover"]:
            return group
        key = (id(group), yard)
        if key in self._support_cache:
            return self._support_cache[key]
        def supported(index: int) -> bool:
            row = self.rows[index]
            shift = yard - row["yardline_100"]
            if kind in ("KICKOFF", "PUNT"):
                if row["touchback"]:
                    distance = row.get("kick_distance")
                    return distance is not None and yard - distance <= 0
                end = row.get("return_end_yardline_100")
                return end is not None and end + shift > 0
            location, returns = row.get("turnover_yardline_100"), row.get("return_yards")
            if location is None or returns is None:
                return False
            location += shift
            if location > 100 or (kind == "INTERCEPTION" and location < -10):
                return False
            if kind != "INTERCEPTION" and location < 0:
                return bool(row["touchback"]) and returns <= 0
            return location + returns > 0 or (location <= 0 and returns <= 0)
        valid = np.asarray([supported(int(index)) for index in group.indices])
        if valid.all():
            selected = group
        elif valid.any():
            weights = group.weights[valid]
            selected = DonorGroup(group.indices[valid], weights, np.cumsum(weights), float(weights.sum()))
        else:
            selected = None
        self._support_cache[key] = selected
        return selected

    def _distribution(self, state: dict[str, Any], scenario: str) -> tuple[list[tuple[DonorGroup, str]], np.ndarray, dict[str, float]]:
        if scenario not in SCENARIOS:
            raise ValueError("scenario must be a declared single-factor sensitivity")
        for key in ("offense_team", "defense_team"):
            if not isinstance(state.get(key), str) or not state[key]:
                raise ValueError(f"missing required team state: {key}")
        season = _required_number(state, "season")
        quarter = _required_number(state, "quarter")
        quarter_seconds = _required_number(state, "quarter_seconds")
        yard = _required_number(state, "yardline_100")
        if season != int(season) or season < 2018 or quarter != int(quarter) or quarter < 1 or not 0 <= quarter_seconds <= 900 or not 0 <= yard <= 100:
            raise ValueError("invalid pre-play season/period/clock/field state")
        context = _context(state)
        cache_key = (context, state["offense_team"], state["defense_team"], int(season), yard, scenario)
        if cache_key in self._cache:
            return self._cache[cache_key]
        choices: list[tuple[DonorGroup, str]] = []
        masses: list[float] = []
        for bank, weight in self._mixture(state):
            for (kind, turnover), group in bank.groups.items():
                # Punt/FG before fourth down are supported only in a final-clock
                # decision window. Kneels/spikes require their actual clock/lead
                # regimes; hierarchy fallback cannot manufacture early kneels.
                if context[0] == "SCRIMMAGE":
                    if kind in ("PUNT", "FIELD_GOAL") and context[1] != 4 and _finite(state.get("half_seconds"), 1800) > 30:
                        continue
                    if kind == "KNEEL" and (_finite(state.get("half_seconds"), 1800) > 120 or _finite(state.get("score_differential"), 0) < 0):
                        continue
                    if kind == "SPIKE" and _finite(state.get("half_seconds"), 1800) > 120:
                        continue
                    if kind == "FIELD_GOAL" and yard + 17 > self.maximum_observed_field_goal_distance:
                        continue  # outside observed Development kick-distance support
                selected = self._supported_group(group, kind, yard)
                if selected is None:
                    continue
                factor = 1.0
                if scenario in ("PASS_HEAVY", "RUN_HEAVY") and kind in PASS_INTENT and context[0] == "SCRIMMAGE":
                    factor = SCENARIOS[scenario]["multiplier"]
                elif scenario == "AGGRESSIVE_FOURTH" and context[0] == "SCRIMMAGE" and context[1] == 4 and kind in GO_INTENT:
                    factor = 1.5
                elif scenario == "ELEVATED_TURNOVER" and turnover:
                    factor = 1.25
                choices.append((selected, kind))
                masses.append(weight * selected.mass / bank.mass * factor)
        if not masses or sum(masses) <= 0:
            raise ValueError("no geometrically and situationally supported play donors")
        mass_array = np.asarray(masses, dtype=float)
        mass_array /= mass_array.sum()
        probabilities = {kind: 0.0 for kind in PLAY_TYPES}
        for (_, kind), mass in zip(choices, mass_array):
            probabilities[kind] += float(mass)
        cumulative = np.cumsum(mass_array)
        cumulative[-1] = 1.0
        result = choices, cumulative, probabilities
        # Bounded cache keeps full-game publication memory predictable.
        if len(self._cache) >= 30000:
            self._cache.clear()
        if len(self._support_cache) >= 30000:
            self._support_cache.clear()
        self._cache[cache_key] = result
        return result

    def probabilities(self, state: dict[str, Any], scenario: str = "BASE") -> dict[str, float]:
        return dict(self._distribution(state, scenario)[2])

    def sample(self, state: dict[str, Any], rng: np.random.Generator, scenario: str = "BASE") -> dict[str, Any]:
        choices, cumulative, _ = self._distribution(state, scenario)
        group, kind = choices[min(int(np.searchsorted(cumulative, rng.random(), side="right")), len(choices) - 1)]
        index = int(group.indices[min(int(np.searchsorted(group.cumulative, rng.random() * group.mass, side="right")), len(group.indices) - 1)])
        donor = self.rows[index]
        result = {key: donor.get(key) for key in OUTCOME_FIELDS}
        shift = _finite(state.get("yardline_100"), 50) - donor["yardline_100"]
        for key in ("ball_end_yardline_100", "turnover_yardline_100", "return_end_yardline_100"):
            if result[key] is not None:
                result[key] += shift
        if kind == "KICKOFF" and result["return_end_yardline_100"] is not None and not result["touchback"]:
            result["receiving_start_yardline_100"] = 100 - result["return_end_yardline_100"]
        if scenario in ("FASTER_PACE", "SLOWER_PACE"):
            result["seconds"] *= SCENARIOS[scenario]["multiplier"]
        result["penalty"] = ({"accepted": True, "yards": result["penalty_yards"], "offense": result["penalty_offense"],
                              "no_play": True, "automatic_first_down": False} if kind == "PENALTY" else None)
        result["donor_evidence"] = {"season": donor["season"], "game_id": donor["game_id"], "play_id": donor["play_id"]}
        result["evidence"] = dict(result["donor_evidence"])
        self.exposure[kind] += 1
        return result

    def metadata(self) -> dict[str, Any]:
        types = Counter(row["type"] for row in self.rows)
        return {"engineId": PLAY_ENGINE, "trainingCutoff": self.training_cutoff, "trainingSeason": self.training_season,
                "cutoffDateExclusive": self.cutoff_date_exclusive, "trainingPlays": self.training_plays,
                "trainingGames": self.training_games, "config": self.config, "scenarios": SCENARIOS,
                "donorCategoryCounts": {kind: types[kind] for kind in PLAY_TYPES}, "donorBankCount": len(self.banks),
                "maximumObservedFieldGoalDistance": self.maximum_observed_field_goal_distance,
                "sampleExposure": dict(self.exposure), "sealedOotRead": False,
                "unsupportedFeatures": ["quarterback identity", "weather", "injuries", "market information", "player tracking"],
                "limitations": ["Hierarchical empirical joint donor model, not a player-level tactical policy or causal simulator.",
                    "No timeout strategy or explicit clock stoppage submodel; elapsed next-live-play clock includes observed runoff.",
                    "Scoring and conversions are reconciled by the legal state engine from sampled progress, not forced to historical flags.",
                    "Cold-start priors are observed league and discounted team-unit distributions; unseen teams use league only."]}


def fit_play_model(plays: pd.DataFrame, *, end_season: int, cutoff_date: str | None = None) -> PlayModel:
    if end_season not in range(2018, 2025):
        raise ValueError("play fitting must stop within Development2018--2024")
    if not plays["season"].isin(range(2018, 2025)).all():
        raise ValueError("input contains a non-Development season")
    cutoff = str(pd.Timestamp(cutoff_date or f"{end_season + 1}-03-01").date())
    train = plays.loc[plays["season"].between(2018, end_season) & plays["date"].lt(cutoff)].copy()
    if train.empty:
        raise ValueError("no strictly pre-cutoff Development play evidence")
    rows = []
    for raw in train.to_dict("records"):
        row = {key: (None if isinstance(value, (float, np.floating)) and not math.isfinite(value) else value) for key, value in raw.items()}
        # Final evaluation labels and source descriptions are not retained even
        # if a caller mistakenly adds them to the normalized frame.
        rows.append({key: value for key, value in row.items() if key in set(OUTCOME_FIELDS) | set(MODEL_CONFIG["covariates"]) |
                     {"game_id", "play_id", "date", "quarter", "quarter_seconds", "season", "type"}})
    weights = np.asarray([.65 ** (end_season - row["season"]) for row in rows], dtype=float)
    index_banks: dict[tuple[Any, ...], list[int]] = {}
    for index, row in enumerate(rows):
        phase, down, distance, field_bin, late, score = _context(row)
        keys = [("phase", phase), ("situation", phase, down, distance),
                ("field", phase, down, distance, field_bin), ("clock", phase, down, distance, field_bin, late, score)]
        for unit, team in (("offense", row["offense_team"]), ("defense", row["defense_team"])):
            keys.extend([(unit, team, phase), (unit, team, phase, down, distance, field_bin)])
        for key in keys:
            index_banks.setdefault(key, []).append(index)
    banks = {key: _make_bank(np.asarray(indices, dtype=np.int32), rows, weights) for key, indices in index_banks.items()}
    maximum_kick = max((_finite(row.get("kick_distance"), row["yardline_100"] + 17)
                        for row in rows if row["type"] == "FIELD_GOAL"), default=0.)
    return PlayModel(rows, banks, str(train["date"].max()), end_season, len(train), int(train["game_id"].nunique()), cutoff, maximum_kick)


def evaluate_play_components(model: PlayModel, valid: pd.DataFrame, *, seed: int = 931071) -> dict[str, Any]:
    """One observed held-out play per context; labels never enter probability input.

    Distribution metrics use reproducible one-donor posterior predictive draws.
    All supported held-out rows are evaluated; no metric-driven refitting occurs.
    """
    if valid.empty or not valid["date"].gt(model.training_cutoff).all() or not valid["season"].gt(model.training_season).all():
        raise ValueError("component validation must be chronologically after the frozen fit")
    if not valid["season"].isin(range(2018, 2025)).all():
        raise ValueError("component validation cannot open Final OOT")
    rng = np.random.default_rng(seed)
    observed = Counter()
    expected = Counter()
    predicted_rows = []
    losses, baseline_losses = [], []
    baseline_counts: dict[str, Counter] = {}
    for row in model.rows:
        baseline_counts.setdefault(row["phase"], Counter())[row["type"]] += 1
    reliability: dict[tuple[str, int], list[float]] = {}
    for row in valid.to_dict("records"):
        state = {key: row[key] for key in MODEL_CONFIG["covariates"] if key in row}
        state.update({"quarter": row["quarter"], "quarter_seconds": row["quarter_seconds"]})
        probabilities = model.probabilities(state)
        target = row["type"]
        observed[target] += 1
        expected.update(probabilities)
        losses.append(-math.log(max(probabilities.get(target, 0), 1e-12)))
        baseline = baseline_counts.get(row["phase"], Counter())
        baseline_losses.append(-math.log(max(baseline[target] / max(1, sum(baseline.values())), 1e-12)))
        for kind, probability in probabilities.items():
            bucket = min(9, int(probability * 10))
            cell = reliability.setdefault((kind, bucket), [0, 0.0, 0.0])
            cell[0] += 1; cell[1] += probability; cell[2] += kind == target
        predicted = model.sample(state, rng)
        predicted["conversion"] = bool(predicted["yards"] >= row["yards_to_go"] and not predicted["turnover"]) if row["phase"] == "SCRIMMAGE" and predicted["type"] in GO_INTENT else False
        predicted_rows.append(predicted)
    simulated = pd.DataFrame(predicted_rows)
    n = len(valid)
    def summary(values: pd.Series) -> dict[str, float]:
        array = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
        return {"count": int(len(array)), "mean": float(array.mean()), "std": float(array.std()),
                **{f"p{q}": float(np.percentile(array, q)) for q in (5, 25, 50, 75, 95)}} if len(array) else {"count": 0}
    rows = [{"type": kind, "observedRate": observed[kind] / n, "meanPredictedProbability": expected[kind] / n,
             "count": observed[kind]} for kind in PLAY_TYPES]
    components = {}
    for label, mask, predmask in (("scrimmageYards", valid["type"].isin(GO_INTENT), simulated["type"].isin(GO_INTENT)),
                                 ("clockSeconds", pd.Series(True, index=valid.index), pd.Series(True, index=simulated.index))):
        column = "seconds" if label == "clockSeconds" else "yards"
        components[label] = {"observed": summary(valid.loc[mask, column]), "simulated": summary(simulated.loc[predmask, column])}
    actual_scrimmage_types = GO_INTENT | {"KNEEL", "SPIKE"}
    scrimmage = valid["type"].isin(actual_scrimmage_types)
    scrimmage_indices = np.flatnonzero(scrimmage.to_numpy())
    first_down = valid["first_down"].astype(bool) & ~valid["turnover"].astype(bool)
    conversion_mask = valid["phase"].eq("SCRIMMAGE") & valid["down"].isin([3, 4]) & ~valid["type"].eq("PENALTY")
    simulated_conversion = simulated.loc[np.flatnonzero(conversion_mask.to_numpy()), "conversion"]
    simulated_scrimmage = simulated["type"].isin(actual_scrimmage_types)
    def rate(values: pd.Series) -> float | None:
        return float(values.mean()) if len(values) else None
    return {"heldoutPlayCount": n, "heldoutSeasons": sorted(int(v) for v in valid["season"].unique()),
            "heldoutDateStart": str(valid["date"].min()), "heldoutDateEnd": str(valid["date"].max()),
            "classOrder": list(PLAY_TYPES), "multiclassLogLoss": float(np.mean(losses)),
            "phaseOnlyUnconditionalBaselineLogLoss": float(np.mean(baseline_losses)),
            "unconditionalBaselineCounts": {phase: dict(counts) for phase, counts in baseline_counts.items()},
            "playTypeCalibration": rows,
            "reliabilityBins": [{"type": kind, "bin": bucket, "count": int(cell[0]),
                                  "meanProbability": cell[1] / cell[0], "observedRate": cell[2] / cell[0]}
                                 for (kind, bucket), cell in sorted(reliability.items())],
            "distributions": components,
            "rates": {"turnover": {"observed": rate(valid.loc[scrimmage, "turnover"]), "simulated": rate(simulated.loc[simulated_scrimmage, "turnover"]),
                                   "denominator": "actual or simulated scrimmage plays, excluding kicks/tries/penalties", "observedPlays": int(scrimmage.sum()), "simulatedPlays": int(simulated_scrimmage.sum())},
                      "sack": {"observed": rate(valid.loc[scrimmage, "type"].eq("SACK")), "simulated": rate(simulated.loc[simulated_scrimmage, "type"].eq("SACK")),
                               "denominator": "actual or simulated scrimmage plays, excluding kicks/tries/penalties"},
                      "firstDownPerScrimmage": {"observed": rate(first_down.loc[scrimmage]), "simulated": rate(simulated.loc[simulated_scrimmage, "conversion"]),
                                               "denominator": "actual or simulated scrimmage plays; turnover plays cannot convert"},
                      "thirdFourthConversion": {"observed": rate(first_down.loc[conversion_mask]), "simulated": rate(simulated_conversion), "observedDecisions": int(conversion_mask.sum()),
                                                "denominator": "all observed third/fourth-down non-penalty decision contexts, including kick choices; turnover plays cannot convert"}},
            "seed": seed, "limitations": ["One posterior-predictive donor per held-out state; distribution metrics carry Monte Carlo error.",
                                             "Component rows condition on historical pre-play states; full-game evaluation is separate."]}
