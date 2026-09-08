"""Renderer-ready traces, path enrichment, selectors and invariance checks.

Everything here is downstream of the fitted samplers. It converts one already
simulated V18 path into a trace a renderer can draw, without changing a single
persisted V18 value.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any, Mapping, Sequence

from server.sports_current_statcast.mlb_v18_play_geometry import (
    COORDINATE_SYSTEM,
    GEOMETRY_MODEL_VERSION,
    RUNNER_MODEL_VERSION,
    SCHEMA_VERSION,
    PlayGeometryError,
    PlayGeometryModel,
    mask_bases,
    template_is_legal,
)

#: Persisted V18 fields the supplement must reproduce byte-identically.
PERSISTED_FIELDS = (
    "pa", "inning", "half", "battingOrderPosition", "pitcherState", "outcome",
    "outsBefore", "outsAfter", "baseMaskBefore", "baseMaskAfter", "runsScored",
    "homeScoreAfter", "awayScoreAfter", "pitchingChange",
)

#: Normalized presentation durations by trajectory. These are sequencing
#: values for an animation, not measured hang times.
_TRACE_DURATION = {
    "GROUND_BALL": 0.45,
    "LINE_DRIVE": 0.55,
    "FLY_BALL": 0.85,
    "POPUP": 0.75,
}

_TRACE_STYLE = {
    "GROUND_BALL": "GROUND",
    "LINE_DRIVE": "LINE",
    "FLY_BALL": "ARC_HIGH",
    "POPUP": "ARC_STEEP",
}

_BASE_ORDER = {"BATTER_BOX": 0, "FIRST": 1, "SECOND": 2, "THIRD": 3, "HOME": 4, "OUT": None}


def _sha(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


# ---------------------------------------------------------------------------
# Ball traces
# ---------------------------------------------------------------------------

def build_ball_trace(geometry: Mapping[str, Any]) -> dict[str, Any] | None:
    """A projected visual trajectory, or None when no ball was put in play.

    The control point is derived deterministically from the batted-ball type
    and the endpoint. It is a drawing aid for a projected path, never a
    measured flight: no launch angle, exit velocity or tracked coordinate
    exists in the registered evidence.
    """

    if not geometry.get("contactOccurred"):
        return None
    point = geometry.get("point")
    if point is None:
        return None

    trajectory = geometry.get("battedBallType") or "LINE_DRIVE"
    end_x, end_y = float(point["x"]), float(point["y"])
    # Arc height scales with the trajectory class and the distance travelled.
    reach = math.hypot(end_x, end_y)
    lift = {
        "GROUND_BALL": 0.0,
        "LINE_DRIVE": 0.10,
        "FLY_BALL": 0.42,
        "POPUP": 0.55,
    }.get(trajectory, 0.2) * max(reach, 0.05)

    control = {
        "x": round(end_x / 2, 6),
        "y": round(end_y / 2, 6),
        # A single normalized "lift" component the renderer may map to an arc
        # height. It carries no physical unit.
        "lift": round(lift, 6),
    }
    return {
        "coordinateSystem": COORDINATE_SYSTEM,
        "start": {"x": 0.0, "y": 0.0},
        "control": [control],
        "end": {"x": round(end_x, 6), "y": round(end_y, 6)},
        "traceStyle": _TRACE_STYLE.get(trajectory, "LINE"),
        "normalizedDuration": _TRACE_DURATION.get(trajectory, 0.6),
        "fairTerritory": bool(point.get("fairTerritory")),
        "outcomeCompatibility": "COMPATIBLE_WITH_PERSISTED_OUTCOME",
        "semantics": (
            "PROJECTED_VISUAL_TRAJECTORY_FROM_SIMULATED_GEOMETRY_"
            "NOT_A_MEASURED_FLIGHT_PATH"
        ),
    }


# ---------------------------------------------------------------------------
# Runner identity continuity
# ---------------------------------------------------------------------------

class RunnerRegistry:
    """Stable anonymous runner ids carried forward across plate appearances.

    An id is minted when a simulated batter reaches base and retired when that
    runner scores or is put out. Ids are deterministic: the same path replayed
    yields the same identities.
    """

    def __init__(self, game_id: str, path_index: int) -> None:
        self._prefix = f"r{_sha([game_id, path_index])[:8]}"
        self._occupants: dict[int, str] = {}
        self._minted = 0

    def occupants(self) -> dict[int, str]:
        return dict(self._occupants)

    def mask(self) -> int:
        mask = 0
        for base in self._occupants:
            mask |= 1 << (base - 1)
        return mask

    def reset_half_inning(self) -> None:
        """A half-inning change clears the bases."""

        self._occupants.clear()

    def sync(self, mask: int) -> None:
        """Force occupancy to a persisted mask, minting ids where needed.

        Used at the start of a half-inning that begins with an automatic
        runner, and as a defensive repair if a template ever left the registry
        inconsistent with persisted state.
        """

        wanted = set(mask_bases(mask))
        for base in list(self._occupants):
            if base not in wanted:
                del self._occupants[base]
        for base in sorted(wanted):
            if base not in self._occupants:
                self._minted += 1
                self._occupants[base] = f"{self._prefix}-{self._minted:02d}"

    def apply(
        self, template: Sequence[tuple[str, str]], *, inning_ends: bool = False,
    ) -> list[dict[str, Any]]:
        """Apply one movement template, returning resolved movements."""

        before = self.occupants()
        moves: list[dict[str, Any]] = []
        destination_map: dict[int, str] = {}

        for origin, destination in template:
            if origin == "BATTER_BOX":
                self._minted += 1
                runner_id = f"{self._prefix}-{self._minted:02d}"
                role = "BATTER"
            else:
                base = _BASE_ORDER[origin]
                runner_id = before.get(base)
                if runner_id is None:
                    # Persisted occupancy said this base was taken; mint rather
                    # than drop the runner.
                    self._minted += 1
                    runner_id = f"{self._prefix}-{self._minted:02d}"
                role = "RUNNER"
            moves.append({
                "anonymousRunnerId": runner_id,
                "role": role,
                "from": origin,
                "to": destination,
                "scored": destination == "HOME",
                "out": destination == "OUT",
            })
            if destination in {"FIRST", "SECOND", "THIRD"}:
                destination_map[_BASE_ORDER[destination]] = runner_id

        # A half-inning that ended strands its survivors: the next state starts
        # with the bases empty, exactly as the transition model defines it.
        self._occupants = {} if inning_ends else destination_map
        return moves


def _movement_reason(
    origin: str, destination: str, outcome: str, *, inning_ends: bool = False,
) -> str:
    if inning_ends and destination not in {"HOME", "OUT"}:
        return "STRANDED_INNING_ENDED"
    if destination == "HOME":
        return "SCORED"
    if destination == "OUT":
        return "BATTER_RETIRED" if origin == "BATTER_BOX" else "RUNNER_RETIRED"
    if origin == "BATTER_BOX":
        return "BATTER_REACHED"
    if _BASE_ORDER[destination] > _BASE_ORDER[origin]:
        return "ADVANCED"
    return "HELD"


def _sequence_movements(moves: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Assign presentation sequencing fractions, lead runner first."""

    ordered = sorted(
        moves,
        key=lambda item: -(_BASE_ORDER[item["from"]] if item["from"] != "BATTER_BOX" else 0),
    )
    total = max(len(ordered), 1)
    sequenced: list[dict[str, Any]] = []
    for position, move in enumerate(ordered):
        start = round(0.12 * position / total, 4)
        distance = 0
        if move["to"] not in {"OUT"}:
            origin = _BASE_ORDER[move["from"]] or 0
            destination = _BASE_ORDER[move["to"]] or origin
            distance = max(destination - origin, 0)
        end = round(min(1.0, start + 0.55 + 0.15 * distance), 4)
        sequenced.append({**move, "startFraction": start, "endFraction": end})
    return sequenced


# ---------------------------------------------------------------------------
# Path enrichment
# ---------------------------------------------------------------------------

def enrich_path(
    *,
    model: PlayGeometryModel,
    path: Sequence[Mapping[str, Any]],
    park: str,
    path_index: int,
    game_id: str,
) -> dict[str, Any]:
    """Add geometry and explicit runner movements to one persisted V18 path."""

    registry = RunnerRegistry(game_id, path_index)
    events: list[dict[str, Any]] = []
    backoff = Counter()
    geometry_backoff = Counter()
    previous_half: tuple[int, str] | None = None

    for position, event in enumerate(path):
        outcome = str(event["outcome"])
        mask_before = int(event["baseMaskBefore"])
        mask_after = int(event["baseMaskAfter"])
        runs = int(event["runsScored"])
        outs_before = int(event["outsBefore"])
        outs_added = int(event["outsAfter"]) - outs_before
        half = (int(event["inning"]), str(event["half"]))

        if previous_half is not None and half != previous_half:
            registry.reset_half_inning()
        previous_half = half
        # The persisted mask is authority; the registry follows it.
        if registry.mask() != mask_before:
            registry.sync(mask_before)

        seed = (game_id, path_index, int(event["pa"]))
        geometry = model.sample_geometry(outcome=outcome, park=park, seed=seed)
        geometry_backoff[geometry.get("geometryBackoffLevel") or "NO_CONTACT"] += 1

        template, level, support = model.sample_runner_template(
            outcome=outcome, mask_before=mask_before, outs_before=outs_before,
            runs=runs, mask_after=mask_after, outs_added=outs_added,
            batted_ball_type=geometry.get("battedBallType"), seed=seed,
        )
        backoff[level] += 1
        if not template_is_legal(
            template, mask_before=mask_before, mask_after=mask_after,
            runs=runs, outs_added=outs_added, outs_before=outs_before,
        ):
            raise PlayGeometryError(f"illegal template emitted at PA {event['pa']}")

        inning_ends = outs_before + outs_added >= 3
        moves = registry.apply(template, inning_ends=inning_ends)
        if registry.mask() != mask_after:
            raise PlayGeometryError(
                f"runner registry diverged from persisted state at PA {event['pa']}"
            )
        movements = [
            {
                **move,
                "movementReason": _movement_reason(
                    move["from"], move["to"], outcome, inning_ends=inning_ends,
                ),
                "authority": (
                    "FITTED_HISTORICAL_TEMPLATE"
                    if level != "DETERMINISTIC_LEGAL_BACKOFF"
                    else "DETERMINISTIC_LEGAL_BACKOFF"
                ),
            }
            for move in moves
        ]

        events.append({
            **{name: event[name] for name in PERSISTED_FIELDS if name in event},
            "battingTeam": "AWAY" if event["half"] == "TOP" else "HOME",
            "geometry": {
                **{key: value for key, value in geometry.items() if key != "point"},
                "landingOrFieldingPoint": geometry.get("point"),
                "coordinateSystem": COORDINATE_SYSTEM,
                "geometryModelVersion": GEOMETRY_MODEL_VERSION,
                "geometrySamplingSeed": _sha(seed)[:16],
            },
            "ballTrace": build_ball_trace(geometry),
            "runnerMovements": _sequence_movements(movements),
            "runnerModelVersion": RUNNER_MODEL_VERSION,
            "runnerBackoffLevel": level,
            "runnerBackoffSupport": support,
        })

    return {
        "schemaVersion": SCHEMA_VERSION,
        "pathIndex": path_index,
        "gameId": game_id,
        "plateAppearances": len(events),
        "events": events,
        "pathDigest": _sha([
            {name: event[name] for name in PERSISTED_FIELDS if name in event}
            for event in path
        ]),
        "geometryDigest": _sha(events),
        "backoffSummary": {
            "runnerTemplates": dict(backoff),
            "geometry": dict(geometry_backoff),
            "runnerBackoffRate": round(
                backoff.get("DETERMINISTIC_LEGAL_BACKOFF", 0) / max(len(events), 1), 6
            ),
        },
    }


# ---------------------------------------------------------------------------
# Representative-path selectors
# ---------------------------------------------------------------------------

#: Predeclared deterministic selection rules. Each is evaluated against the
#: enriched candidate paths; a selector with no qualifying game is reported
#: unsatisfied rather than filled with an approximation.
SELECTORS: Mapping[str, str] = {
    "TYPICAL": (
        "Minimum absolute distance to the population expected total runs and "
        "expected run differential."
    ),
    "HOME_WIN": "Home team ahead at the final state, nearest the home-win conditional medians.",
    "AWAY_WIN": "Away team ahead at the final state, nearest the away-win conditional medians.",
    "HIGH_SCORING": "Nearest the conditional 90th percentile of total runs, not the maximum.",
    "LOW_SCORING": "Nearest the conditional 10th percentile of total runs, not necessarily 0-0.",
    "EXTRA_INNINGS": "Tied after regulation; representative among extra-inning games.",
}


def _final_state(path: Mapping[str, Any]) -> dict[str, Any]:
    events = path["events"]
    last = events[-1]
    return {
        "awayScore": int(last["awayScoreAfter"]),
        "homeScore": int(last["homeScoreAfter"]),
        "innings": int(last["inning"]),
        "totalRuns": int(last["awayScoreAfter"]) + int(last["homeScoreAfter"]),
        "differential": int(last["homeScoreAfter"]) - int(last["awayScoreAfter"]),
        "extraInnings": int(last["inning"]) > 9,
    }


def select_representative_paths(
    paths: Sequence[Mapping[str, Any]], forecast: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply every predeclared selector to the available enriched paths."""

    expected_total = float(forecast.get("meanTotalRuns") or 0.0)
    expected_differential = float(forecast.get("meanRunDifferential") or 0.0)
    candidates = [{"path": path, "final": _final_state(path)} for path in paths]

    satisfied: dict[str, Any] = {}
    unavailable: dict[str, str] = {}
    #: A selector is only meaningful when there is a population to select FROM.
    #: With a single retained path every rule trivially returns that path, which
    #: would misrepresent one trace as six representative games.
    degenerate = len(candidates) < 2

    def choose(name: str, pool: Sequence[Mapping[str, Any]], key) -> None:
        if not pool:
            unavailable[name] = (
                "No retained simulated path qualifies for this selector. The "
                "accepted bundle persists only its representative trace, so the "
                "remaining selectors require a new Development-only trace "
                "generation against the accepted configuration."
            )
            return
        if degenerate:
            unavailable[name] = (
                "Only one simulated path is retained, so this selector would "
                "trivially return that single path. It is reported unsatisfied "
                "rather than presenting one trace as a selected representative."
            )
            return
        best = min(pool, key=key)
        satisfied[name] = {
            "rule": SELECTORS[name],
            "pathIndex": best["path"]["pathIndex"],
            "pathDigest": best["path"]["pathDigest"],
            "geometryDigest": best["path"]["geometryDigest"],
            "finalState": best["final"],
        }

    choose("TYPICAL", candidates, lambda item: (
        abs(item["final"]["totalRuns"] - expected_total)
        + abs(item["final"]["differential"] - expected_differential)
    ))
    choose("HOME_WIN", [c for c in candidates if c["final"]["differential"] > 0],
           lambda item: abs(item["final"]["totalRuns"] - expected_total))
    choose("AWAY_WIN", [c for c in candidates if c["final"]["differential"] < 0],
           lambda item: abs(item["final"]["totalRuns"] - expected_total))

    totals = sorted(item["final"]["totalRuns"] for item in candidates)
    if totals:
        high = totals[min(len(totals) - 1, int(round(0.9 * (len(totals) - 1))))]
        low = totals[int(round(0.1 * (len(totals) - 1)))]
        choose("HIGH_SCORING", candidates, lambda item: abs(item["final"]["totalRuns"] - high))
        choose("LOW_SCORING", candidates, lambda item: abs(item["final"]["totalRuns"] - low))
    else:
        choose("HIGH_SCORING", [], lambda item: 0)
        choose("LOW_SCORING", [], lambda item: 0)

    choose("EXTRA_INNINGS", [c for c in candidates if c["final"]["extraInnings"]],
           lambda item: abs(item["final"]["totalRuns"] - expected_total))

    return {
        "selectors": dict(SELECTORS),
        "candidatePathCount": len(candidates),
        "selectionDegenerate": degenerate,
        "enrichedPaths": [
            {
                "pathIndex": item["path"]["pathIndex"],
                "pathDigest": item["path"]["pathDigest"],
                "geometryDigest": item["path"]["geometryDigest"],
                "plateAppearances": item["path"]["plateAppearances"],
                "finalState": item["final"],
                "backoffSummary": item["path"]["backoffSummary"],
            }
            for item in candidates
        ],
        "satisfied": satisfied,
        "unavailable": unavailable,
        "note": (
            "No selected path is a prediction of the real game. Each is one "
            "simulated member of the V18 population chosen by a predeclared rule."
        ),
    }


# ---------------------------------------------------------------------------
# V18 invariance
# ---------------------------------------------------------------------------

def verify_v18_invariance(
    forecast: Mapping[str, Any], enriched: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Prove the supplement changed no accepted V18 value or state."""

    accepted_paths = forecast.get("traces") or []
    checks: list[dict[str, Any]] = []
    all_held = True

    for position, (original, path) in enumerate(zip(accepted_paths, enriched)):
        mismatches = []
        for index, (before, after) in enumerate(zip(original, path["events"])):
            for name in PERSISTED_FIELDS:
                if name in before and before[name] != after.get(name):
                    mismatches.append({"pa": before.get("pa"), "field": name})
        held = not mismatches and len(original) == len(path["events"])
        all_held &= held
        checks.append({
            "pathIndex": position,
            "plateAppearancesBefore": len(original),
            "plateAppearancesAfter": len(path["events"]),
            "persistedFieldMismatches": mismatches[:10],
            "held": held,
        })

    population = {
        name: forecast.get(name)
        for name in (
            "homeWinProbability", "meanHomeRuns", "meanAwayRuns", "meanTotalRuns",
            "meanRunDifferential", "oneRunRate", "extraInningRate",
            "simulationCount", "masterSeed", "paFold", "transitionFold",
            "illegalStateCount", "nonterminationCount",
        )
    }
    return {
        "parentBundleSha256": forecast.get("bundleSha256") or None,
        "populationValuesReadOnly": population,
        "perPathChecks": checks,
        "allInvariantsHeld": bool(all_held),
        "statement": (
            "The supplement reads the accepted forecast and writes a separate "
            "artifact. No V18 probability, expected run, PA outcome, state "
            "transition, final score, simulation count or seed was modified."
        ),
    }
