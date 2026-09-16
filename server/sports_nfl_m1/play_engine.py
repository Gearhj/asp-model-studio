"""Independent, donor-conditioned play simulator with explicit football state.

The fitted model samples *joint* play evidence; this module applies rules to the
new state, never copies a donor game's result. No player identities are invented.
Clock durations represent sampled game-clock intervals, not physical travel time.
"""
from __future__ import annotations

import copy
import math
from collections import Counter
from typing import Any

import numpy as np

ENGINE_ID = "NFL_DEVELOPMENT_HIERARCHICAL_PLAY_V1"
RULES_URL = "https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf"
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
RUSH_TYPES = {"RUSH", "QB_SNEAK", "QB_SCRAMBLE", "KNEEL"}
PASS_TYPES = {"PASS_COMPLETE", "PASS_INCOMPLETE", "INTERCEPTION", "SPIKE"}
SCRIMMAGE_TYPES = RUSH_TYPES | PASS_TYPES | {"SACK"}
LABELS = {
    "RUSH": "Rush", "QB_SNEAK": "Quarterback sneak", "QB_SCRAMBLE": "Quarterback scramble",
    "KNEEL": "Kneel-down", "PASS_COMPLETE": "Completed pass", "PASS_INCOMPLETE": "Incomplete pass",
    "INTERCEPTION": "Interception", "SPIKE": "Spike", "SACK": "Sack", "PUNT": "Punt",
    "FIELD_GOAL": "Field-goal attempt", "EXTRA_POINT": "Extra-point attempt",
    "TWO_POINT": "Two-point attempt", "KICKOFF": "Kickoff", "PENALTY": "Penalty / no play",
    "PERIOD_END": "Period transition",
}


class IllegalPlayState(ValueError):
    """No impossible path is silently repaired or published."""


def other(side: str) -> str:
    return "AWAY" if side == "HOME" else "HOME"


def score_key(side: str) -> str:
    return "homeScore" if side == "HOME" else "awayScore"


def remaining(state: dict) -> float:
    return float(state["clockSeconds"] + (4-state["quarter"])*900) if state["quarter"] <= 4 else float(state["clockSeconds"])


def model_state(state: dict, home: str, away: str, season: int) -> dict:
    offense_home = state["possession"] == "HOME"
    return {"phase": state["phase"], "offense_team": home if offense_home else away,
            "defense_team": away if offense_home else home, "season": season,
            "quarter": state["quarter"], "quarter_seconds": state["clockSeconds"],
            "half_seconds": state["clockSeconds"]+(900 if state["quarter"] in (1, 3) else 0),
            "down": state["down"], "yards_to_go": state["distance"],
            "yardline_100": state["yardline100"],
            "score_differential": state[score_key(state["possession"])]-state[score_key(other(state["possession"]))]}


def _finite(value: Any, field: str) -> float:
    if value is None or not math.isfinite(float(value)):
        raise IllegalPlayState(f"missing/nonfinite modeled {field}")
    return float(value)


def _field(value: float) -> float:
    # Football goal-line absorption: this is explicit boundary censoring, not
    # missing-value imputation or a fictitious historical measurement.
    return round(max(0., min(100., value)), 6)


def _new_series(state: dict, side: str, yardline: float) -> None:
    if not math.isfinite(yardline) or not 0 < yardline < 100:
        raise IllegalPlayState("new series requires an interior spot; unsupported endzone administration")
    state.update(possession=side, yardline100=yardline,
                 phase="SCRIMMAGE", down=1)
    state["distance"] = min(10., state["yardline100"])


def _kickoff(state: dict, kicking: str, *, safety: bool = False) -> None:
    state.update(possession=kicking, phase="KICKOFF", down=0, distance=0.,
                 yardline100=80. if safety else 65.)


def _touchdown(state: dict, side: str) -> None:
    state[score_key(side)] += 6
    state.update(possession=side, phase="TRY", down=0, distance=2., yardline100=2.)


def apply_play(state: dict, sample: dict, *, season: int) -> tuple[dict, dict]:
    """Pure single-event state transition, independently testable from fitting.

    All outcome yard lines use the BEFORE-possession distance-to-opponent frame.
    The AFTER state always uses its own current possession frame.
    """
    before = dict(state)
    result = dict(state)
    side, opponent = before["possession"], other(before["possession"])
    start = float(before["yardline100"])
    kind = str(sample["type"])
    if kind not in LABELS or kind == "PERIOD_END":
        raise IllegalPlayState(f"unsupported sampled play category {kind}")
    permitted = {"KICKOFF": {"KICKOFF"}, "TRY": {"EXTRA_POINT", "TWO_POINT"},
                 "SCRIMMAGE": SCRIMMAGE_TYPES | {"PUNT", "FIELD_GOAL", "PENALTY"}}
    if kind not in permitted.get(before["phase"], set()):
        raise IllegalPlayState(f"{kind} cannot occur in phase {before['phase']}")
    seconds = max(0., _finite(sample["seconds"], "seconds"))
    if before["phase"] == "TRY": seconds = 0.  # Untimed try by rule.
    elif kind == "FIELD_GOAL": seconds = min(5., max(1., seconds))
    elif kind == "PENALTY": seconds = 0.  # Supported presnap, no-play subset only.
    elif kind != "KICKOFF": seconds = max(1., seconds)
    seconds = min(float(before["clockSeconds"]), seconds)
    result["clockSeconds"] = round(max(0., before["clockSeconds"]-seconds), 6)
    out = {"seconds": seconds, "sampledSeconds": float(sample["seconds"]),
           "yardsGained": 0., "endYardline100": start, "turnover": False,
           "turnoverDowns": False, "fumble": bool(sample.get("fumble", False)),
           "fumbleLost": bool(sample.get("fumble_lost", False)),
           "firstDown": False, "possessionEnded": False, "scoringType": None,
           "scoringTeam": None, "turnoverYardline100": None, "returnEndYardline100": None,
           "supportTreatments": [], "airYards": sample.get("air_yards")}
    if sample.get("air_yards") is not None:
        out["targetYardline100"] = _field(start-_finite(sample["air_yards"], "air yards"))

    if kind == "PENALTY":
        penalty = sample.get("penalty")
        if not penalty or not penalty.get("no_play") or "offense" not in penalty:
            raise IllegalPlayState("only identified presnap no-play penalties supported")
        penalty_yards = abs(_finite(penalty.get("yards"), "penalty yards"))
        offense = bool(penalty["offense"])
        available = (100-start) if offense else start
        assessed = min(penalty_yards, available/2.) if penalty_yards > available/2. else penalty_yards
        end = start+assessed if offense else start-assessed
        result["yardline100"] = end
        result["distance"] = min(end, before["distance"]+assessed if offense else max(0., before["distance"]-assessed))
        if not offense and (penalty.get("automatic_first_down") or result["distance"] <= 0):
            _new_series(result, side, end); out["firstDown"] = True
        out.update(endYardline100=end, penalty={**penalty, "assessedYards": assessed})
    elif kind in ("EXTRA_POINT", "TWO_POINT"):
        good = bool(sample.get("kick_success", sample.get("success", False)))
        points = (1 if kind == "EXTRA_POINT" else 2) if good else 0
        result[score_key(side)] += points
        out.update(endYardline100=0. if good else start, kickSuccess=good,
                   scoringType=("XP" if kind == "EXTRA_POINT" else "TWO_POINT") if good else None,
                   scoringTeam=side if good else None, possessionEnded=True)
        _kickoff(result, side)
    elif kind == "FIELD_GOAL":
        good = bool(sample.get("kick_success", False))
        out.update(endYardline100=0., kickSuccess=good, possessionEnded=True,
                   kickDistance=start+17., supportTreatments=["STANDARD_SEVEN_YARD_HOLD_OFFSET; NO_BLOCK_OR_MISSED_KICK_RETURN"])
        if good:
            result[score_key(side)] += 3
            out.update(scoringType="FG", scoringTeam=side)
            _kickoff(result, side)
        else:
            # Dead missed kick: spot of kick, or receiving own20 if closer.
            kick_spot = min(100., start+7.)
            _new_series(result, opponent, min(80., 100.-kick_spot))
            out["nextPossessionSpotPreFrame"] = 100.-result["yardline100"]
    elif kind in ("KICKOFF", "PUNT"):
        kick_distance = _finite(sample.get("kick_distance", sample.get("yards")), "kick distance")
        raw_landing = start-max(0., kick_distance)
        landing = _field(raw_landing)
        out.update(kickDistance=kick_distance, endYardline100=landing,
                   turnoverYardline100=landing, possessionEnded=True)
        touchback = bool(sample.get("touchback"))
        if touchback:
            if raw_landing > 0:
                raise IllegalPlayState("transported kick touchback did not reach the endzone")
            own_spot = (35 if season >= 2025 else 30 if season == 2024 else 25) if kind == "KICKOFF" else 20
            if kind == "KICKOFF" and start == 80: own_spot = 20
            _new_series(result, opponent, 100.-own_spot)
            out.update(touchback=True, returnEndYardline100=None,
                       nextPossessionSpotPreFrame=float(own_spot))
            out["supportTreatments"].append("STANDARD_RULE_ERA_TOUCHBACK; LANDING_ZONE_EXCEPTION_NOT_IDENTIFIED")
        else:
            return_yards = _finite(sample.get("return_yards"), "kick return yards")
            end = _field(raw_landing+return_yards)
            out.update(returnEndYardline100=end, returnYards=return_yards)
            if raw_landing != landing:
                out["supportTreatments"].append("ENDZONE_KICK_LANDING_CLIPPED_FOR_FIELD_RENDER; RETURN_USES_UNCLIPPED_LOCATION")
            if end >= 100:
                _touchdown(result, opponent)
                out.update(scoringType="TD", scoringTeam=opponent)
            else:
                _new_series(result, opponent, 100.-end)
            if kind == "KICKOFF" and start == 80:
                out["supportTreatments"].append("SAFETY_FREE_KICK_USES_LEAGUE_KICK_DISTANCE_RETURN_PRIOR")
    else:
        yards = 0. if kind in ("PASS_INCOMPLETE", "SPIKE", "INTERCEPTION") else _finite(sample.get("yards"), "play yards")
        end = _field(start-yards)
        if kind == "SACK" and yards > 0: raise IllegalPlayState("positive-yard sack donor")
        if end != start-yards: out["supportTreatments"].append("GOAL_LINE_ABSORBING_BOUNDARY")
        out.update(yardsGained=start-end, endYardline100=end)
        lost = kind == "INTERCEPTION" or out["fumbleLost"]
        if lost:
            if kind == "INTERCEPTION":
                if sample.get("air_yards") is None:
                    raise IllegalPlayState("interception geometry requires modeled air yards")
                raw_location = start-float(sample["air_yards"])
            else:
                # Fumble net yards do not locate recovery. The model transports
                # an explicitly observed donor recovery offset into this state.
                raw_location = _finite(sample.get("turnover_yardline_100"), "fumble recovery location")
            location = _field(raw_location)
            return_yards = _finite(sample.get("return_yards"), "turnover return yards")
            returned = _field(raw_location+return_yards)
            out.update(turnover=True, possessionEnded=True, turnoverYardline100=location,
                       returnEndYardline100=returned, returnYards=return_yards,
                       endYardline100=location)
            if returned >= 100:
                _touchdown(result, opponent)
                out.update(scoringType="TD", scoringTeam=opponent)
            elif location <= 0 and return_yards <= 0:
                _new_series(result, opponent, 80.)
                out.update(touchback=True, nextPossessionSpotPreFrame=20., returnEndYardline100=None)
            else:
                _new_series(result, opponent, 100.-returned)
        elif end <= 0 and kind not in ("PASS_INCOMPLETE", "SPIKE"):
            _touchdown(result, side)
            out.update(scoringType="TD", scoringTeam=side, firstDown=True, possessionEnded=True)
        elif end >= 100 and kind not in ("PASS_INCOMPLETE", "SPIKE"):
            result[score_key(opponent)] += 2
            _kickoff(result, side, safety=True)
            out.update(scoringType="SAFETY", scoringTeam=opponent, possessionEnded=True)
        elif start-end >= before["distance"]:
            _new_series(result, side, end)
            out["firstDown"] = True
        elif before["down"] == 4:
            _new_series(result, opponent, 100.-end)
            out.update(turnoverDowns=True, possessionEnded=True)
        else:
            result.update(yardline100=end, down=before["down"]+1,
                          distance=min(end, before["distance"]-(start-end)))
        if out["fumble"] and not lost:
            out["supportTreatments"].append("RECOVERED_BY_SAME_OFFENSE; NO_INDIVIDUAL_RECOVERER_IDENTITY")

    result["gameSecondsRemaining"] = remaining(result)
    out["homePointsAdded"] = result["homeScore"]-before["homeScore"]
    out["awayPointsAdded"] = result["awayScore"]-before["awayScore"]
    if before["down"] in (3, 4) and kind in SCRIMMAGE_TYPES:
        out["conversionDown"] = before["down"]
        out["converted"] = bool(out["firstDown"] and not out["turnover"])
    if sample.get("evidence") is not None: out["samplingEvidence"] = sample["evidence"]
    return result, out


def description(play: dict, home: str, away: str) -> str:
    before, out = play["stateBefore"], play["outcome"]
    team = home if before["possession"] == "HOME" else away
    kind = play["playType"]
    if kind == "PERIOD_END": return str(out["transitionReason"])
    parts = [f"{team}: {LABELS[kind]}"]
    if kind in SCRIMMAGE_TYPES and kind not in ("INTERCEPTION", "PASS_INCOMPLETE", "SPIKE"):
        parts.append(f"{out['yardsGained']:g} yards")
    if out["fumble"]: parts.append("fumble, recovered by opponent" if out["fumbleLost"] else "fumble, recovered by same offense")
    if out.get("returnYards") is not None: parts.append(f"{out['returnYards']:g}-yard modeled return")
    if out.get("touchback"): parts.append("touchback")
    if out["turnoverDowns"]: parts.append("turnover on downs")
    if out["scoringType"]:
        scorer = home if out["scoringTeam"] == "HOME" else away
        parts.append(f"{scorer} {out['scoringType']}")
    elif kind in ("FIELD_GOAL", "EXTRA_POINT", "TWO_POINT"): parts.append("unsuccessful")
    if out["firstDown"] and not out["scoringType"]: parts.append("first down")
    return "; ".join(parts)+". Simulated, anonymous players."


def assert_state(state: dict) -> None:
    if state["possession"] not in ("HOME", "AWAY") or state["phase"] not in ("SCRIMMAGE", "KICKOFF", "TRY", "FINAL"):
        raise IllegalPlayState("invalid possession or phase")
    if state["quarter"] not in range(1, 6): raise IllegalPlayState("invalid quarter")
    limit = 600 if state["quarter"] == 5 else 900
    if not 0 <= state["clockSeconds"] <= limit: raise IllegalPlayState("invalid quarter clock")
    if not 0 <= state["yardline100"] <= 100: raise IllegalPlayState("ball outside field")
    if not 0 <= state["distance"] <= state["yardline100"]: raise IllegalPlayState("distance beyond opponent goal")
    if state["phase"] == "SCRIMMAGE" and (state["down"] not in (1, 2, 3, 4) or state["distance"] <= 0):
        raise IllegalPlayState("invalid scrimmage down/distance")
    if state["phase"] != "SCRIMMAGE" and state["down"] != 0: raise IllegalPlayState("special event down must be zero")
    if any(not isinstance(state[key], int) or state[key] < 0 for key in ("homeScore", "awayScore")):
        raise IllegalPlayState("negative or noninteger score")
    if abs(remaining(state)-state["gameSecondsRemaining"]) > 1e-5:
        raise IllegalPlayState("game/quarter clock disagreement")


def verify_game(game: dict) -> dict:
    previous = None
    sums = [0, 0]
    for i, play in enumerate(game["plays"], 1):
        b, a, out = play["stateBefore"], play["stateAfter"], play["outcome"]
        assert_state(b); assert_state(a)
        if play["playNumber"] != i or (previous is not None and previous != b):
            raise IllegalPlayState("discontinuous play state")
        if play["playType"] != "PERIOD_END":
            if a["quarter"] != b["quarter"] or abs(b["clockSeconds"]-out["seconds"]-a["clockSeconds"]) > 1e-5:
                raise IllegalPlayState("invalid in-play clock progression")
            added = [out["homePointsAdded"], out["awayPointsAdded"]]
            expected_points = {None: 0, "TD": 6, "FG": 3, "XP": 1, "TWO_POINT": 2, "SAFETY": 2}[out["scoringType"]]
            if sum(added) != expected_points or any(n < 0 for n in added) or all(n > 0 for n in added):
                raise IllegalPlayState("invalid scoring event")
            if play["playType"] in ("PASS_INCOMPLETE", "SPIKE") and out["yardsGained"] != 0:
                raise IllegalPlayState("incomplete pass advanced field position")
            if out["turnover"] and not (out["turnoverYardline100"] is not None):
                raise IllegalPlayState("turnover location absent")
            if out["turnoverDowns"] and not (b["down"] == 4 and not out["firstDown"] and a["possession"] != b["possession"]):
                raise IllegalPlayState("invalid turnover on downs")
        else:
            if out["homePointsAdded"] or out["awayPointsAdded"] or out["seconds"]:
                raise IllegalPlayState("period transition invented score or play clock")
            if a["phase"] != "FINAL" and b["clockSeconds"] != 0:
                raise IllegalPlayState("period ended before clock expired")
        sums[0] += out["homePointsAdded"]; sums[1] += out["awayPointsAdded"]
        if [a["homeScore"], a["awayScore"]] != sums:
            raise IllegalPlayState("score reconciliation differs")
        previous = a
    if not previous or previous["phase"] != "FINAL" or sums != [game["homeScore"], game["awayScore"]]:
        raise IllegalPlayState("incomplete final state")
    return {"impossibleStateCount": 0, "scoreReconciliationMismatch": 0, "playsChecked": len(game["plays"])}


def _diagnostics(plays: list[dict]) -> dict:
    live = [p for p in plays if p["playType"] != "PERIOD_END"]
    scrim = [p for p in live if p["playType"] in SCRIMMAGE_TYPES]
    passing = [p for p in live if p["playType"] in PASS_TYPES]
    drives = {p["driveNumber"] for p in live if p["stateBefore"]["phase"] == "SCRIMMAGE"}
    yards = [p["outcome"]["yardsGained"] for p in scrim]
    clocks = [p["outcome"]["seconds"] for p in live if p["playType"] not in ("PENALTY", "EXTRA_POINT", "TWO_POINT")]
    return {"scrimmagePlays": len(scrim), "firstDowns": sum(p["outcome"]["firstDown"] for p in scrim),
            "turnovers": sum(p["outcome"]["turnover"] for p in live),
            "sacks": sum(p["playType"] == "SACK" for p in live),
            "rushPlays": sum(p["playType"] in RUSH_TYPES for p in live),
            "passAttempts": len(passing), "completions": sum(p["playType"] == "PASS_COMPLETE" for p in live),
            "offensiveYards": sum(yards), "clockSeconds": sum(clocks), "clockIntervalCount": len(clocks),
            "drives": len(drives), "points": sum(p["outcome"]["homePointsAdded"]+p["outcome"]["awayPointsAdded"] for p in live),
            "playTypeCounts": dict(Counter(p["playType"] for p in live)),
            "yardHistogram": dict(Counter(str(v) for v in yards)), "clockHistogram": dict(Counter(str(round(v, 1)) for v in clocks)),
            "thirdDownAttempts": sum(p["outcome"].get("conversionDown") == 3 for p in live),
            "thirdDownConversions": sum(p["outcome"].get("conversionDown") == 3 and p["outcome"].get("converted", False) for p in live),
            "fourthDownAttempts": sum(p["outcome"].get("conversionDown") == 4 for p in live),
            "fourthDownConversions": sum(p["outcome"].get("conversionDown") == 4 and p["outcome"].get("converted", False) for p in live),
            "supportTreatmentCounts": dict(Counter(x for p in live for x in p["outcome"]["supportTreatments"])),
            "impossibleStateCount": 0}


def decorate_game(game: dict) -> dict:
    from .play_geometry import geometry_for_play
    result = copy.deepcopy(game)
    for play in result["plays"]: play["geometry"] = geometry_for_play(play)
    return result


def simulate_play_game(model: Any, *, home_team: str, away_team: str, season: int,
                       seed: int, scenario: str = "BASE", postseason: bool = False,
                       include_geometry: bool = True) -> dict:
    if postseason: raise ValueError("play V1 publication is regular-season only; postseason OT not modeled")
    if scenario not in SCENARIOS: raise ValueError("scenario was not predeclared")
    if season == 2025: raise ValueError("sealed 2025 season is not a simulation/evaluation target")
    if home_team == away_team: raise ValueError("home/away must be distinct")
    rng = np.random.default_rng(seed)
    opening_receiver = "HOME" if rng.integers(2) == 0 else "AWAY"
    state = {"possession": other(opening_receiver), "quarter": 1, "clockSeconds": 900.,
             "gameSecondsRemaining": 3600., "down": 0, "distance": 0., "yardline100": 65.,
             "homeScore": 0, "awayScore": 0, "phase": "KICKOFF"}
    sequence: list[dict] = []
    drive_number = 1
    regulation_score = None
    ot_seen: set[str] = set()
    ot_first_receiver = None
    pending_try = None

    def append(kind: str, before: dict, after: dict, out: dict) -> None:
        play = {"playNumber": len(sequence)+1, "driveNumber": drive_number, "playType": kind,
                "stateBefore": dict(before), "stateAfter": dict(after), "outcome": out}
        play["description"] = description(play, home_team, away_team)
        sequence.append(play)

    def transition(reason: str, after: dict) -> None:
        out = {"transitionReason": reason, "seconds": 0., "homePointsAdded": 0, "awayPointsAdded": 0,
               "endYardline100": state["yardline100"], "turnover": False, "scoringType": None}
        after["gameSecondsRemaining"] = remaining(after)
        append("PERIOD_END", state, after, out)
        state.update(after)

    def finish(reason: str) -> None:
        after = {**state, "phase": "FINAL", "down": 0, "distance": 0.}
        transition(reason, after)

    while state["phase"] != "FINAL":
        if len(sequence) > 1500: raise IllegalPlayState("game failed to terminate within safety bound; no artifact may publish")
        assert_state(state)
        if state["clockSeconds"] <= 0 and state["phase"] != "TRY":
            q = state["quarter"]
            if q in (1, 3):
                transition(f"End of quarter {q}; possession and series continue", {**state, "quarter": q+1, "clockSeconds": 900.})
            elif q == 2:
                after = {**state, "quarter": 3, "clockSeconds": 900.}
                _kickoff(after, opening_receiver)
                transition("Halftime; opposite opening receiver receives second-half kickoff", after)
                drive_number += 1
            elif q == 4:
                regulation_score = (state["homeScore"], state["awayScore"])
                if regulation_score[0] != regulation_score[1]: finish("Regulation complete")
                else:
                    ot_first_receiver = "HOME" if rng.integers(2) == 0 else "AWAY"
                    after = {**state, "quarter": 5, "clockSeconds": 600.}
                    _kickoff(after, other(ot_first_receiver))
                    transition("Regulation tie; regular-season ten-minute overtime", after)
                    drive_number += 1
            else: finish("Regular-season overtime clock expired")
            continue
        before = dict(state)
        if state["quarter"] == 5:
            if state["phase"] == "SCRIMMAGE": ot_seen.add(state["possession"])
            elif state["phase"] == "KICKOFF": ot_seen.add(other(state["possession"]))
        if state["phase"] == "TRY" and pending_try is not None:
            sampled, pending_try = pending_try, None
        else:
            sampled = model.sample(model_state(state, home_team, away_team, season), rng, scenario)
        after, outcome = apply_play(state, sampled, season=season)
        if after["phase"] == "TRY":
            # Choose the try once before placing its succeeding state. Selection
            # excludes the action-dependent15/2-yard spot; a frozen donor provides
            # the chosen try's success, and no second draw changes that decision.
            pending_try = model.sample(model_state(after, home_team, away_team, season), rng, scenario)
            if pending_try["type"] not in ("EXTRA_POINT", "TWO_POINT"):
                raise IllegalPlayState("try sampler returned an invalid action")
            spot = 15. if pending_try["type"] == "EXTRA_POINT" else 2.
            after.update(yardline100=spot, distance=spot)
        append(sampled["type"], before, after, outcome)
        state = after

        if state["quarter"] == 5 and outcome["turnover"]:
            ot_seen.add(other(before["possession"]))
        ot_end = False
        if state["quarter"] == 5 and state["homeScore"] != state["awayScore"]:
            if outcome["scoringTeam"] and outcome["scoringTeam"] != before["possession"] and before["phase"] == "SCRIMMAGE":
                ot_end = True
            elif season < 2025 and len(ot_seen) == 1 and outcome["scoringType"] == "TD":
                ot_end = True
            elif len(ot_seen) >= 2:
                if state["phase"] == "TRY":
                    # Allow a responding TD's try if it can tie or take the lead.
                    scoring_side = state["possession"]
                    diff = state[score_key(scoring_side)]-state[score_key(other(scoring_side))]
                    ot_end = diff > 0 or diff < -2
                else:
                    ot_end = bool((outcome["possessionEnded"] and before["phase"] != "KICKOFF") or outcome["scoringType"])
        # Do not perform an unnecessary try after an expired winning touchdown.
        if state["quarter"] in (4, 5) and state["clockSeconds"] <= 0 and state["phase"] == "TRY":
            scoring_side = state["possession"]
            diff = state[score_key(scoring_side)]-state[score_key(other(scoring_side))]
            if diff > 0 or diff < -2: ot_end = True
        if ot_end:
            if state["quarter"] == 4: regulation_score = (state["homeScore"], state["awayScore"])
            finish("Game-winning score or completed overtime opportunity; no unnecessary try")
        elif outcome["possessionEnded"] and state["phase"] != "TRY" and before["phase"] != "KICKOFF":
            drive_number += 1

    regulation_score = regulation_score or (state["homeScore"], state["awayScore"])
    game = {"schemaVersion": "NFL_PLAY_LEVEL_GAME_V1", "homeTeam": home_team, "awayTeam": away_team,
            "homeScore": state["homeScore"], "awayScore": state["awayScore"],
            "regulationHomeScore": regulation_score[0], "regulationAwayScore": regulation_score[1],
            "reachedOvertime": state["quarter"] == 5, "regulationTie": regulation_score[0] == regulation_score[1],
            "finalTie": state["homeScore"] == state["awayScore"], "seed": seed, "scenarioId": scenario,
            "plays": sequence, "diagnostics": _diagnostics(sequence)}
    game["diagnostics"].update(verify_game(game))
    return decorate_game(game) if include_geometry else game
