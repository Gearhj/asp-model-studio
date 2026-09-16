"""Schematic renderer evidence for the independent play-level research engine.

Longitudinal endpoints are modeled football facts. Lateral offsets and Bezier
control points are deterministic layout, never fitted routes, player tracking,
air yards, ball-flight heights, or measured physics. Nothing here executes a
model, reads football data, or changes a simulated football state.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

CONTRACT_VERSION = "NFL_LABS_PLAY_LEVEL_CONTRACT_V1"
ARTIFACT_VERSION = "NFL_LABS_PLAY_LEVEL_SIMULATION_V1"
GEOMETRY_VERSION = "NFL_MODELED_PLAY_GEOMETRY_V1"
FAMILY = "nfl-labs-play-level-supplements"
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "shared" / "contracts" / f"{CONTRACT_VERSION}.json"
PLAY_TYPES = frozenset({"RUSH", "QB_SNEAK", "QB_SCRAMBLE", "PASS_COMPLETE", "PASS_INCOMPLETE", "SACK",
    "INTERCEPTION", "PUNT", "FIELD_GOAL", "EXTRA_POINT", "TWO_POINT", "KICKOFF", "KNEEL", "SPIKE",
    "PENALTY", "PERIOD_END"})
STATE_FIELDS = ("possession", "quarter", "clockSeconds", "gameSecondsRemaining", "down", "distance",
                "yardline100", "homeScore", "awayScore", "phase")
SCORE_FIELDS = ("homeScore", "awayScore")
AUTHORITY = {"status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
             "wageringAuthority": False, "executionAllowedInAISP": False}


class PlayGeometryError(ValueError):
    """A rendered record would claim unsupported or inconsistent football facts."""


def _number(value: Any, field: str, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PlayGeometryError(f"{field} must be a finite number")
    number = float(value)
    if low is not None and number < low or high is not None and number > high:
        raise PlayGeometryError(f"{field} outside [{low}, {high}]")
    return number


def _integer(value: Any, field: str, low: int = 0, high: int | None = None) -> int:
    number = _number(value, field, low, high)
    if number != int(number):
        raise PlayGeometryError(f"{field} must be an integer")
    return int(number)


def _state(state: Mapping[str, Any], label: str) -> None:
    if not isinstance(state, Mapping) or any(key not in state for key in STATE_FIELDS):
        raise PlayGeometryError(f"{label} lacks complete state fields")
    if state["possession"] not in ("HOME", "AWAY"):
        raise PlayGeometryError(f"{label}.possession must be HOME or AWAY")
    quarter = _integer(state["quarter"], f"{label}.quarter", 1, 5)
    _number(state["clockSeconds"], f"{label}.clockSeconds", 0, 600 if quarter == 5 else 900)
    _number(state["gameSecondsRemaining"], f"{label}.gameSecondsRemaining", 0, 3600)
    down = _integer(state["down"], f"{label}.down", 0, 4)
    _number(state["distance"], f"{label}.distance", 0, 100)
    _number(state["yardline100"], f"{label}.yardline100", 0, 100)
    for key in SCORE_FIELDS:
        _integer(state[key], f"{label}.{key}")
    if state["phase"] not in ("SCRIMMAGE", "KICKOFF", "TRY", "FINAL"):
        raise PlayGeometryError(f"{label}.phase unsupported")
    if state["phase"] == "SCRIMMAGE" and down == 0:
        raise PlayGeometryError(f"{label}: scrimmage requires down 1--4")


def field_x(yardline100: float, possession: str) -> float:
    """Global schematic yards from left goal; HOME attacks left, AWAY right."""
    value = _number(yardline100, "yardline100", 0, 100)
    if possession not in ("HOME", "AWAY"):
        raise PlayGeometryError("unknown possession coordinate frame")
    return value if possession == "HOME" else 100.0 - value


def _point(x: float, y: float) -> dict[str, float]:
    return {"x": round(x, 6), "y": round(y, 6)}


def _segment(kind: str, start: float, end: float, lateral: float, *, possession: str,
             y_start: float = .5, y_end: float = .5) -> dict[str, Any]:
    if kind in ("PASS_OUTCOME_CURVE", "PASS_MODELED_AIR_CURVE", "PUNT_ARC", "KICKOFF_ARC", "FIELD_GOAL_ARC", "TRY_KICK_ARC"):
        controls = [_point(start + (end-start)/3, .5+lateral), _point(start + 2*(end-start)/3, .5+lateral)]
        interpolation = "CUBIC_BEZIER"
    elif kind in ("RUSH_GROUND", "QB_SCRAMBLE_GROUND", "RETURN_GROUND", "MODELED_YAC_GROUND"):
        controls = [_point(start + (end-start)*.35, .5+lateral/2), _point(start + (end-start)*.7, .5-lateral/3)]
        interpolation = "POLYLINE"
    else:
        controls = []
        interpolation = "LINEAR"
    return {"kind": kind, "possession": possession, "possessionDirection": "LEFT" if possession == "HOME" else "RIGHT", "interpolation": interpolation,
            "start": _point(start, y_start), "controlPoints": controls, "end": _point(end, y_end),
            "longitudinalBasis": "MODELED_PLAY_ENDPOINTS",
            "lateralBasis": "SCHEMATIC_LAYOUT_NOT_FITTED_ROUTE",
            "physicalTrajectory": False}


def geometry_for_play(event: Mapping[str, Any]) -> dict[str, Any]:
    """Produce deterministic paths from explicit outcomes, never post-flip spots.

    ``endYardline100``, ``turnoverYardline100`` and ``returnEndYardline100``
    must all be in the PRE-play possession coordinate frame. An incomplete
    pass without a separately modeled target gets an unlocated-pass glyph,
    not an invented catch point or trajectory. Pass completion curves describe
    whole-play advancement; no unmodeled catch/YAC split is asserted.
    """
    before, after = event["stateBefore"], event["stateAfter"]
    _state(before, "stateBefore")
    _state(after, "stateAfter")
    kind = event["playType"]
    if kind not in PLAY_TYPES:
        raise PlayGeometryError(f"unsupported playType {kind}")
    play_number = _integer(event["playNumber"], "playNumber", 1)
    _integer(event["driveNumber"], "driveNumber", 0)
    outcome = event["outcome"]
    possession = before["possession"]
    defense = "AWAY" if possession == "HOME" else "HOME"
    start = field_x(before["yardline100"], possession)
    locations = {}
    for name in ("endYardline100", "turnoverYardline100", "returnEndYardline100", "targetYardline100"):
        raw = outcome.get(name)
        locations[name] = None if raw is None else field_x(raw, possession)
    end = locations["endYardline100"]
    turnover = bool(outcome.get("turnover") or outcome.get("fumbleLost"))
    turnover_location = locations["turnoverYardline100"]
    return_end = locations["returnEndYardline100"]
    if return_end is not None and turnover_location is None:
        raise PlayGeometryError("modeled return endpoint requires explicit recovery/turnover location")
    if return_end is not None and not (turnover or kind in ("PUNT", "KICKOFF")):
        raise PlayGeometryError("return endpoint supplied without possession-changing play")
    sack_net_endpoint = None
    if kind == "SACK" and outcome.get("fumbleLost"):
        # A lost-fumble recovery spot can be forward of the line even when the
        # net sack statistic is nonpositive. It is not the initial fumble spot.
        # Keep these separate instead of turning a recovery into forward sack
        # movement or inventing a loose-ball path to connect the two locations.
        net_sack_yards = _number(outcome.get("yardsGained"), "sack net yards")
        if net_sack_yards > 1e-9:
            raise PlayGeometryError("sack net yards must not move the offense forward")
        sack_net_endpoint = field_x(float(before["yardline100"]) - net_sack_yards, possession)
    elif kind == "SACK" and end is not None:
        signed_gain = float(before["yardline100"]) - float(outcome["endYardline100"])
        if signed_gain > 1e-9:
            raise PlayGeometryError("sack endpoint must not move the offense forward")
    # Stable alternating offsets are renderer layout only, not football randomness.
    lateral = (.14 if play_number % 2 else -.14)
    paths: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    limitations = ["Lateral offsets and curve control points are schematic, not fitted routes or measured tracking.",
                  "Each play is laterally re-centered; cross-play lateral continuity is not asserted."]
    target = turnover_location if turnover_location is not None else end
    no_motion = kind in ("PERIOD_END", "SPIKE") or (kind == "PENALTY" and outcome.get("noPlay", True))
    if no_motion:
        path_type = "NO_BALL_MOTION"
        markers.append({"kind": "PERIOD_BOUNDARY" if kind == "PERIOD_END" else kind,
                        "point": _point(start, .5), "basis": "MODELED_EVENT_STATE"})
    elif kind == "PASS_INCOMPLETE":
        if locations["targetYardline100"] is not None:
            path_type = "INCOMPLETE_PASS_TARGET_CURVE"
            paths.append(_segment("PASS_OUTCOME_CURVE", start, locations["targetYardline100"], lateral, possession=possession))
        else:
            path_type = "INCOMPLETE_PASS_UNLOCATED"
            markers.append({"kind": "INCOMPLETE_PASS", "point": _point(start, .5), "basis": "LINE_OF_SCRIMMAGE_NOT_PASS_TARGET"})
            limitations.append("Incomplete-pass target was not modeled; no target, flight distance or return-to-line ball path is invented.")
    elif sack_net_endpoint is not None:
        path_type = "SACK_NET_AND_SEPARATE_FUMBLE_RECOVERY"
        if abs(sack_net_endpoint-start) > 1e-9:
            net_segment = _segment("SACK_NET_BACKWARD", start, sack_net_endpoint, 0., possession=possession)
            net_segment["longitudinalBasis"] = "MODELED_NET_SACK_YARDS_NOT_FUMBLE_LOCATION"
            paths.append(net_segment)
        else:
            markers.append({"kind": "SACK_NET_ZERO", "point": _point(start, .5),
                            "basis": "MODELED_NET_SACK_STATISTIC_NOT_INITIAL_FUMBLE_POINT"})
        limitations.append("Lost-fumble sack net yards are shown separately from the modeled recovery location. The initial fumble point and loose-ball flight are unavailable; do not connect the net-sack endpoint to the recovery marker. A zero net statistic does not imply a stationary quarterback.")
    elif target is None:
        path_type = "ENDPOINT_UNAVAILABLE"
        limitations.append("Terminal ball location was not supplied; ball movement is unmaterialized.")
    else:
        path_type = {"PASS_COMPLETE": "PASS_OUTCOME_CURVE", "INTERCEPTION": "PASS_OUTCOME_CURVE",
                     "RUSH": "RUSH_GROUND", "QB_SNEAK": "QB_SNEAK_GROUND", "QB_SCRAMBLE": "QB_SCRAMBLE_GROUND",
                     "SACK": "SACK_BACKWARD", "KNEEL": "KNEEL_GROUND", "PUNT": "PUNT_ARC",
                     "KICKOFF": "KICKOFF_ARC", "FIELD_GOAL": "FIELD_GOAL_ARC", "EXTRA_POINT": "TRY_KICK_ARC",
                     "TWO_POINT": "TRY_OUTCOME_GROUND", "PENALTY": "ENFORCEMENT_NO_PHYSICAL_PATH"}[kind]
        if path_type == "ENFORCEMENT_NO_PHYSICAL_PATH":
            markers.extend([{"kind": "PENALTY_PRE_SPOT", "point": _point(start, .5), "basis": "MODELED_ENFORCEMENT"},
                            {"kind": "PENALTY_ENFORCED_SPOT", "point": _point(target, .5), "basis": "MODELED_ENFORCEMENT"}])
        elif kind == "PASS_COMPLETE" and locations["targetYardline100"] is not None:
            path_type = "PASS_WITH_MODELED_AIR_AND_YAC"
            catch = locations["targetYardline100"]
            air_path = _segment("PASS_MODELED_AIR_CURVE", start, catch, lateral, possession=possession)
            air_path["longitudinalBasis"] = "MODELED_AIR_YARDS_AND_NET_YARDS"
            paths.append(air_path)
            if abs(catch-target) > 1e-9:
                ground_path = _segment("MODELED_YAC_GROUND", catch, target, lateral/2, possession=possession)
                ground_path["longitudinalBasis"] = "MODELED_AIR_YARDS_AND_NET_YARDS"
                paths.append(ground_path)
            markers.append({"kind": "MODELED_CATCH", "point": _point(catch, .5),
                            "basis": "MODELED_AIR_YARDS_AND_NET_YARDS; NOT_PLAYER_TRACKING"})
        else:
            paths.append(_segment(path_type, start, target, lateral, possession=possession))
        if kind == "PASS_COMPLETE" and locations["targetYardline100"] is None:
            limitations.append("Pass curve is a whole-play outcome connector, not a fitted air/YAC split or physical flight.")
        elif kind == "PASS_COMPLETE":
            limitations.append("Air and net yardage define the longitudinal catch/ground split; their curves remain schematic, not physical flight or player routes. Negative modeled yards after catch are retained.")
        elif kind == "INTERCEPTION":
            limitations.append("The pass segment ends at the explicit modeled interception location; its curve is schematic, not physical flight.")
    if turnover_location is not None:
        markers.append({"kind": "TURNOVER" if turnover else "FUMBLE_RECOVERY" if outcome.get("fumble") else "KICK_RECEIPT", "point": _point(turnover_location, .5),
                        "basis": "EXPLICIT_MODELED_LOCATION"})
    elif turnover:
        limitations.append("Turnover location is unavailable; no return movement is invented.")
    if return_end is not None:
        paths.append(_segment("RETURN_GROUND", turnover_location, return_end, -lateral,
                              possession=defense))
    if outcome.get("fumble"):
        markers.append({"kind": "FUMBLE_LOST" if outcome.get("fumbleLost") else "FUMBLE_RECOVERED",
                        "point": _point(turnover_location if turnover_location is not None else target, .5) if turnover_location is not None or target is not None else None,
                        "basis": "MODELED_OUTCOME; LOCATION_ONLY_WHEN_EXPLICIT"})
    if outcome.get("turnoverDowns"):
        markers.append({"kind": "TURNOVER_ON_DOWNS", "point": _point(end, .5) if end is not None else None,
                        "basis": "MODELED_FOURTH_DOWN_OUTCOME; NO_RETURN_PATH"})
    scoring_type = outcome.get("scoringType")
    scoring_endpoint = None
    if scoring_type:
        # An awarded score identifies a goal by rules, not by fabricated tracking.
        home_points = outcome.get("homePointsAdded", 0)
        away_points = outcome.get("awayPointsAdded", 0)
        scoring_team = "HOME" if home_points > 0 else "AWAY" if away_points > 0 else None
        if scoring_team is None:
            raise PlayGeometryError("scoringType requires a recorded score increment")
        # A safety occurs at the opponent's own goal, which is also the goal
        # attacked by the scoring team in this fixed schematic orientation.
        goal = 0.0 if scoring_team == "HOME" else 100.0
        scoring_endpoint = {"kind": scoring_type, "point": _point(goal, .5), "scoringTeam": scoring_team,
                            "basis": "SCORING_RULE_MARKER_NOT_TRACKED_ENDPOINT"}
        markers.append(scoring_endpoint)
    return {"schemaVersion": GEOMETRY_VERSION, "classification": "MODELED_VISUALIZATION_NOT_MEASURED_TRACKING",
            "coordinateSystem": "X_YARDS_FROM_LEFT_GOAL_Y_NORMALIZED_SCHEMATIC_WIDTH",
            "possession": possession, "possessionDirection": "LEFT" if possession == "HOME" else "RIGHT",
            "playType": kind, "ballPathType": path_type,
            "startYardline100": before["yardline100"], "endYardline100": outcome.get("endYardline100"),
            "endpointCoordinateFrame": "PRE_PLAY_POSSESSION_DISTANCE_TO_OPPONENT_GOAL",
            "segments": paths, "markers": markers,
            "turnoverLocation": _point(turnover_location, .5) if turnover_location is not None else None,
            "returnEndpoint": _point(return_end, .5) if return_end is not None else None,
            "scoringEndpoint": scoring_endpoint,
            "clockBefore": {"quarter": before["quarter"], "seconds": before["clockSeconds"]},
            "clockAfter": {"quarter": after["quarter"], "seconds": after["clockSeconds"]},
            "downDistanceBefore": {"down": before["down"], "distance": before["distance"]},
            "downDistanceAfter": {"down": after["down"], "distance": after["distance"]},
            "scoreBefore": {key: before[key] for key in SCORE_FIELDS},
            "scoreAfter": {key: after[key] for key in SCORE_FIELDS},
            "description": str(event.get("description", kind.replace("_", " ").capitalize())),
            "playerIdentities": None, "measuredTracking": False, "limitations": limitations}


def validate_play_sequence(plays: Sequence[Mapping[str, Any]], *, final_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Strict snapshot/clock/score/geometry continuity; deeper rules live in engine.

    PERIOD_END explicitly records quarter transitions. Field-placement changes
    for kicks/tries and possession flips cannot be hidden between adjacent plays.
    """
    if not plays:
        raise PlayGeometryError("complete representative requires plays")
    previous = None
    previous_drive = 0
    score_increments = {"homeScore": 0, "awayScore": 0}
    geometry_count = 0
    for index, play in enumerate(plays, 1):
        if _integer(play.get("playNumber"), "playNumber", 1) != index:
            raise PlayGeometryError("play numbers must be contiguous from 1")
        drive = _integer(play.get("driveNumber"), "driveNumber", 0)
        if drive < previous_drive or drive > previous_drive + 1:
            raise PlayGeometryError("drive numbers must be nondecreasing without gaps")
        before, after = play["stateBefore"], play["stateAfter"]
        _state(before, "stateBefore")
        _state(after, "stateAfter")
        if previous is not None and before != previous:
            raise PlayGeometryError(f"state continuity failure before play {index}")
        if before["phase"] == "FINAL":
            raise PlayGeometryError("play occurs after FINAL state")
        outcome = play["outcome"]
        seconds = _number(outcome["seconds"], "outcome.seconds", 0)
        if play["playType"] == "PERIOD_END":
            if (before["clockSeconds"] != 0 and after["phase"] != "FINAL") or seconds != 0:
                raise PlayGeometryError("period boundary requires expired clock and zero elapsed seconds")
            if after["quarter"] != before["quarter"] + 1 and after["phase"] != "FINAL":
                raise PlayGeometryError("period boundary must advance one quarter or finish")
        else:
            if after["quarter"] != before["quarter"]:
                raise PlayGeometryError("quarter change requires explicit PERIOD_END")
            if abs(float(before["clockSeconds"]) - float(after["clockSeconds"]) - seconds) > 1e-7:
                raise PlayGeometryError("clock consumption does not reconcile")
        for key, delta_field in (("homeScore", "homePointsAdded"), ("awayScore", "awayPointsAdded")):
            delta = _integer(outcome[delta_field], delta_field, 0, 6)
            if after[key] - before[key] != delta:
                raise PlayGeometryError("score delta does not reconcile")
            score_increments[key] += delta
        generated = geometry_for_play(play)
        if "geometry" in play and play["geometry"] != generated:
            raise PlayGeometryError("stored geometry differs from deterministic modeled endpoints")
        geometry_count += len(generated["segments"])
        previous, previous_drive = after, drive
    if final_state is not None and previous != final_state:
        raise PlayGeometryError("declared final state differs from last play")
    if previous["phase"] != "FINAL":
        raise PlayGeometryError("complete representative does not finish in FINAL state")
    initial = plays[0]["stateBefore"]
    if any(initial[key] + score_increments[key] != previous[key] for key in SCORE_FIELDS):
        raise PlayGeometryError("complete-game score reconciliation failed")
    return {"plays": len(plays), "geometrySegments": geometry_count, "stateDiscontinuities": 0,
            "scoreReconciliationExact": True, "geometryReproductionExact": True,
            "finalScore": {"home": previous["homeScore"], "away": previous["awayScore"]}}


def load_contract() -> dict[str, Any]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("schemaVersion") != CONTRACT_VERSION:
        raise PlayGeometryError("unexpected play-level contract version")
    return contract


def validate_contract_schema(artifact: Mapping[str, Any]) -> None:
    """Validate the exact JSON-Schema vocabulary used by this local contract.

    No optional JSON-Schema dependency or remote schema resolution is needed.
    Standard importers can validate the same embedded Draft2020-12 schema.
    """
    root = load_contract()["jsonSchema"]

    def check(value: Any, schema: Mapping[str, Any], path: str) -> None:
        if "$ref" in schema:
            reference = schema["$ref"]
            if not reference.startswith("#/$defs/"):
                raise PlayGeometryError("only local contract schema references are supported")
            check(value, root["$defs"][reference.rsplit("/", 1)[1]], path)
        for subschema in schema.get("allOf", []):
            check(value, subschema, path)
        if "const" in schema and (value != schema["const"] or isinstance(schema["const"], bool) and type(value) is not bool):
            raise PlayGeometryError(f"{path}: schema constant differs")
        if "enum" in schema and value not in schema["enum"]:
            raise PlayGeometryError(f"{path}: value outside schema enum")
        declared = schema.get("type")
        types = [declared] if isinstance(declared, str) else declared or []
        predicates = {"object": isinstance(value, Mapping), "array": isinstance(value, list),
                      "string": isinstance(value, str), "null": value is None,
                      "boolean": type(value) is bool,
                      "integer": type(value) is int,
                      "number": type(value) in (int, float) and math.isfinite(value)}
        if types and not any(predicates.get(kind, False) for kind in types):
            raise PlayGeometryError(f"{path}: schema type differs, expected {types}")
        if isinstance(value, Mapping):
            for field in schema.get("required", []):
                if field not in value:
                    raise PlayGeometryError(f"{path}: schema required field missing: {field}")
            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is False and set(value)-set(properties):
                raise PlayGeometryError(f"{path}: undeclared schema fields")
            for key, subschema in properties.items():
                if key in value:
                    check(value[key], subschema, f"{path}.{key}")
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                raise PlayGeometryError(f"{path}: insufficient schema items")
            if "items" in schema:
                for index, item in enumerate(value):
                    check(item, schema["items"], f"{path}[{index}]")
        if type(value) in (int, float):
            if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
                raise PlayGeometryError(f"{path}: schema numeric bound violated")
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                raise PlayGeometryError(f"{path}: empty schema string")
            if schema.get("format") == "date-time":
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError("timezone absent")
                except ValueError as error:
                    raise PlayGeometryError(f"{path}: timezone-aware timestamp required") from error

    check(artifact, root, "artifact")


def validate_play_level_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the independent play-level envelope and every representative.

    Population calibration and legal-state evaluation remain separate engine
    validation. This function does not execute or reconstruct a fitted model.
    """
    contract = load_contract()
    for field in contract["requiredArtifactFields"]:
        if field not in artifact:
            raise PlayGeometryError(f"missing artifact field {field}")
    validate_contract_schema(artifact)
    if artifact["schemaVersion"] != ARTIFACT_VERSION or artifact["sport"] != "NFL":
        raise PlayGeometryError("artifact is not the new NFL play-level family")
    for key, expected in AUTHORITY.items():
        if type(artifact[key]) is not type(expected) or artifact[key] != expected:
            raise PlayGeometryError(f"research-only authority differs: {key}")
    count = _integer(artifact["drawCount"], "drawCount", 1)
    population = artifact["populationFinals"]
    if len(population) != count:
        raise PlayGeometryError("population count differs from drawCount")
    by_id = {}
    for game in population:
        identity = _integer(game["simulationIndex"], "population.simulationIndex", 0)
        if identity in by_id:
            raise PlayGeometryError("duplicate population simulation identity")
        by_id[identity] = game
        for field in SCORE_FIELDS:
            _integer(game[field], f"population.{field}")
    representatives = artifact["simulatedGames"]
    if len(representatives) < 6:
        raise PlayGeometryError("at least six complete representatives required")
    if len({game["simulationIndex"] for game in representatives}) != len(representatives):
        raise PlayGeometryError("representative simulation identities must be distinct")
    reports = []
    for game in representatives:
        if game["simulationIndex"] not in by_id:
            raise PlayGeometryError("representative not in supplied population")
        population_game = by_id[game["simulationIndex"]]
        for field in SCORE_FIELDS:
            if game[field] != population_game[field]:
                raise PlayGeometryError("representative score differs from population member")
        if "seed" in population_game and game["seed"] != population_game["seed"]:
            raise PlayGeometryError("representative seed differs from population member")
        report = validate_play_sequence(game["plays"], final_state=game.get("finalState"))
        if report["finalScore"] != {"home": game["homeScore"], "away": game["awayScore"]}:
            raise PlayGeometryError("representative final score differs from complete plays")
        reports.append(report)
    encoded = json.dumps(artifact, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"schemaVersion": "NFL_PLAY_LEVEL_CONTRACT_VERIFICATION_V1", "artifactVersion": ARTIFACT_VERSION,
            "populationGames": count, "representatives": len(representatives),
            "plays": sum(item["plays"] for item in reports), "allRepresentativeStatesContinuous": True,
            "allRepresentativeScoresExact": True, "allGeometryReproduces": True,
            "canonicalLogicalSha256": hashlib.sha256(encoded).hexdigest()}
