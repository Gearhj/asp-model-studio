"""V18 Play Geometry trace supplement: modelled geometry and explicit runners.

WHAT THIS IS
------------
A state-consistent enrichment layer for V18 sequential simulation paths. Given a
plate appearance V18 already sampled -- its outcome, before/after outs, before/
after base mask and runs scored -- this samples a historically fitted, legal
batted-ball geometry and an explicit anonymous runner-movement template that are
compatible with that already-authoritative play.

WHAT THIS IS NOT
----------------
It is not a replacement for the V18 PA outcome model and it does not decide any
V18 result. It never changes a win probability, an expected run total, a PA
outcome, a state transition or a final score. The accepted bundle is read-only
input; the supplement is published separately.

EVIDENCE BOUNDARY
-----------------
The registered Development authority (FD1 ``play_transition``, Retrosheet
lineage) records:

  * the play's own outcome, before/after outs, before/after base mask, runs
  * explicit runner identifiers on each base BEFORE and AFTER the play, so
    runner advancement is *recovered*, never guessed
  * Retrosheet ``event_text``, which encodes batted-ball trajectory (ground,
    line, fly, popup) and a fielding-location zone with a depth modifier

It does NOT record exit velocity, launch angle in degrees, spray angle in
degrees, landing distance in feet, or any tracked (x, y) coordinate. Those
fields are therefore reported as UNSUPPORTED and emitted as null. What this
module emits instead is a zone-derived direction and depth, explicitly labelled
as a Retrosheet location zone centroid rather than a measurement.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "MLB_V18_PLAY_GEOMETRY_TRACE_V1"
COORDINATE_SYSTEM = "ASP_NORMALIZED_DIAMOND_V1"
GEOMETRY_MODEL_VERSION = "MLB_V18_PLAY_GEOMETRY_SAMPLER_V1"
RUNNER_MODEL_VERSION = "MLB_V18_RUNNER_TEMPLATE_SAMPLER_V1"

PARENT_BUNDLE_ID = "mlb-v18-whole-game-a6e7e99122f1b60701a4728b"
PARENT_BUNDLE_SHA256 = (
    "a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27"
)

#: Fields the registered Development authority does not carry. They are emitted
#: as null with this reason attached; nothing here ever fabricates them.
UNSUPPORTED_GEOMETRY_FIELDS: Mapping[str, str] = {
    "exitVelocityMph": "FD1/Retrosheet play_transition retains no launch_speed.",
    "launchAngleDegrees": "FD1/Retrosheet play_transition retains no launch_angle.",
    "sprayAngleDegrees": (
        "No tracked spray angle is registered; a zone-derived direction is "
        "emitted as sprayDirectionDegrees instead."
    ),
    "projectedDistanceFeet": (
        "No hit_distance_sc is registered; a zone depth class is emitted "
        "instead."
    ),
    "landingCoordinateMeasured": (
        "No hc_x/hc_y tracking coordinate is registered; the emitted point is a "
        "location-zone centroid."
    ),
}


class PlayGeometryError(RuntimeError):
    """A geometry or runner-movement invariant failed."""


# ---------------------------------------------------------------------------
# 1. Retrosheet event parsing
# ---------------------------------------------------------------------------

#: Retrosheet trajectory letters, in the order they may appear in a location.
_TRAJECTORY = {"G": "GROUND_BALL", "L": "LINE_DRIVE", "F": "FLY_BALL", "P": "POPUP"}

#: A batted-ball location: trajectory letter, then zone digits, then modifiers.
_LOCATION = re.compile(r"(?<![A-Za-z])([GLFP])([1-9]{1,2})(XD|D|S|M|L|F)*")

#: The part of an event before the first advancement segment.
_ADVANCE_SPLIT = re.compile(r"\.")


@dataclass(frozen=True)
class ParsedEvent:
    """Batted-ball geometry recovered from one Retrosheet event string."""

    contact: bool
    trajectory: str | None
    zone: str | None
    depth: str | None
    foul: bool
    fielders: tuple[int, ...]
    raw: str

    @property
    def has_location(self) -> bool:
        return self.zone is not None


def parse_event_text(event_text: str | None) -> ParsedEvent:
    """Recover trajectory, zone and depth from a Retrosheet event string.

    Returns ``contact=False`` for strikeouts, walks and hit-by-pitch, which
    carry no batted ball and must never receive a ball trace.
    """

    raw = (event_text or "").strip()
    if not raw:
        return ParsedEvent(False, None, None, None, False, (), raw)

    head = _ADVANCE_SPLIT.split(raw, 1)[0]
    # Non-contact events. 'K' may be followed by a modifier ('K23', 'K+WP').
    if re.match(r"^(K|W|IW|HP|HBP)([^A-Za-z0-9]|$|\+|[0-9])", head) or head in {"K", "W", "IW", "HP"}:
        return ParsedEvent(False, None, None, None, False, (), raw)
    # Purely baserunning events carry no plate appearance at all.
    if re.match(r"^(SB|CS|PO|POCS|WP|PB|BK|DI|OA|FLE|NP)", head):
        return ParsedEvent(False, None, None, None, False, (), raw)

    match = _LOCATION.search(head)
    trajectory = zone = depth = None
    foul = False
    if match:
        trajectory = _TRAJECTORY.get(match.group(1))
        zone = match.group(2)
        modifiers = re.findall(r"XD|D|S|M|L|F", match.group(0)[1 + len(match.group(2)):])
        foul = "F" in modifiers
        depth = next((item for item in ("XD", "D", "S", "M") if item in modifiers), None)
    fielders = tuple(int(digit) for digit in re.findall(r"[1-9]", head.split("/")[0]))
    return ParsedEvent(True, trajectory, zone, depth, foul, fielders, raw)


# ---------------------------------------------------------------------------
# 2. Coordinate system
# ---------------------------------------------------------------------------

#: Direction of each Retrosheet zone, in degrees from the centre-field axis.
#: Negative is toward left field, positive toward right field. These are zone
#: centroids for a documented, deterministic transformation -- not measurements.
_ZONE_DIRECTION: Mapping[str, float] = {
    "1": 0.0, "2": 0.0,
    "3": 27.0, "34": 18.0, "4": 9.0, "5": -27.0, "56": -18.0, "6": -9.0,
    "7": -30.0, "78": -15.0, "8": 0.0, "89": 15.0, "9": 30.0,
    "23": 12.0, "25": -12.0, "15": -14.0, "13": 14.0, "46": 0.0,
}

#: Nominal depth of each zone before the depth modifier is applied, as a
#: fraction of the centre-field reference distance.
_ZONE_DEPTH: Mapping[str, float] = {
    "1": 0.12, "2": 0.04, "3": 0.20, "34": 0.26, "4": 0.28, "5": 0.20,
    "56": 0.26, "6": 0.28, "46": 0.30,
    "7": 0.62, "78": 0.66, "8": 0.70, "89": 0.66, "9": 0.62,
    "23": 0.10, "25": 0.10, "15": 0.14, "13": 0.14,
}

_DEPTH_SCALE: Mapping[str | None, float] = {
    "S": 0.80, "M": 1.00, None: 1.00, "D": 1.16, "XD": 1.30,
}

_DEPTH_CLASS: Mapping[str | None, str] = {
    "S": "SHALLOW", "M": "MEDIUM", None: "UNMODIFIED", "D": "DEEP", "XD": "EXTRA_DEEP",
}

#: Fielding position fallback when a play records fielders but no location.
_FIELDER_ZONE: Mapping[int, str] = {
    1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9",
}

COORDINATE_SYSTEM_DEFINITION: Mapping[str, Any] = {
    "name": COORDINATE_SYSTEM,
    "origin": "HOME_PLATE",
    "originPoint": {"x": 0.0, "y": 0.0},
    "axes": {
        "x": "Positive toward the first-base/right-field side, negative toward third base/left field.",
        "y": "Positive along the home-plate-to-centre-field axis.",
    },
    "units": (
        "Dimensionless. 1.0 on the centre-field axis is the nominal centre-field "
        "reference distance. No value is expressed in feet."
    ),
    "foulLines": {"leftFieldDegrees": -45.0, "rightFieldDegrees": 45.0},
    "centreFieldAxisDegrees": 0.0,
    "fairTerritory": "abs(directionDegrees) <= 45",
    "transformation": (
        "Retrosheet trajectory letter -> battedBallType. Retrosheet location "
        "zone -> zone centroid direction in degrees and nominal depth; the "
        "depth modifier (S/M/D/XD) scales the depth. x = depth * sin(direction), "
        "y = depth * cos(direction)."
    ),
    "clipping": (
        "Depth is clipped to [0.02, 1.35]. A point outside fair territory is "
        "retained with fairTerritory=false and must be drawn in foul ground."
    ),
    "nullBehaviour": (
        "contactOccurred=false yields null for every geometry field and no ball "
        "trace. A contact play with no recorded location yields a null point, "
        "geometryAuthority=UNLOCATED_CONTACT and no ball trace."
    ),
    "presentationNote": (
        "No CSS colour or pixel dimension is defined here. The consumer maps "
        "this normalized system onto its own field drawing."
    ),
}


def zone_to_point(zone: str | None, depth_modifier: str | None) -> dict[str, Any] | None:
    """Deterministic zone centroid in the normalized coordinate system."""

    if zone is None:
        return None
    direction = _ZONE_DIRECTION.get(zone)
    nominal = _ZONE_DEPTH.get(zone)
    if direction is None or nominal is None:
        return None
    depth = max(0.02, min(1.35, nominal * _DEPTH_SCALE.get(depth_modifier, 1.0)))
    radians = math.radians(direction)
    return {
        "x": round(depth * math.sin(radians), 6),
        "y": round(depth * math.cos(radians), 6),
        "directionDegrees": round(direction, 3),
        "depth": round(depth, 6),
        "depthClass": _DEPTH_CLASS.get(depth_modifier, "UNMODIFIED"),
        "fairTerritory": abs(direction) <= 45.0,
    }


# ---------------------------------------------------------------------------
# 3. Runner movement recovery from registered evidence
# ---------------------------------------------------------------------------

BASE_STATES = ("BATTER_BOX", "FIRST", "SECOND", "THIRD", "HOME", "OUT")
_BASE_INDEX = {"FIRST": 1, "SECOND": 2, "THIRD": 3}
_INDEX_BASE = {1: "FIRST", 2: "SECOND", 3: "THIRD"}


def mask_bases(mask: int) -> tuple[int, ...]:
    """Occupied bases from a 3-bit mask: 1=first, 2=second, 4=third."""

    if mask < 0 or mask > 7:
        raise PlayGeometryError(f"base mask out of range: {mask}")
    return tuple(base for base in (1, 2, 3) if mask & (1 << (base - 1)))


def bases_mask(bases: Iterable[int]) -> int:
    mask = 0
    for base in bases:
        mask |= 1 << (base - 1)
    return mask


@dataclass(frozen=True)
class RunnerMovement:
    """One runner's explicit movement across a plate appearance."""

    anonymous_runner_id: str
    role: str
    from_state: str
    to_state: str
    scored: bool
    out: bool
    movement_reason: str
    authority: str

    def as_dict(self, start_fraction: float, end_fraction: float) -> dict[str, Any]:
        return {
            "anonymousRunnerId": self.anonymous_runner_id,
            "role": self.role,
            "from": self.from_state,
            "to": self.to_state,
            "scored": self.scored,
            "out": self.out,
            "movementReason": self.movement_reason,
            "startFraction": round(start_fraction, 4),
            "endFraction": round(end_fraction, 4),
            "authority": self.authority,
        }


def observed_runner_template(row: Mapping[str, Any]) -> tuple[tuple[str, str], ...] | None:
    """Recover the explicit (from, to) template from registered runner ids.

    FD1 records the identifier occupying each base before and after the play, so
    a real historical advancement is *read*, not inferred. Returns None when the
    identifiers are incomplete for the recorded occupancy.
    """

    before = {}
    after = {}
    for base, key in ((1, "first"), (2, "second"), (3, "third")):
        before_id = row.get(f"runner_on_{key}_before")
        after_id = row.get(f"runner_on_{key}_after")
        if before_id:
            before[str(before_id)] = base
        if after_id:
            after[str(after_id)] = base

    mask_before = int(row.get("base_mask_before") or 0)
    mask_after = int(row.get("base_mask_after") or 0)
    if bases_mask(before.values()) != mask_before:
        return None
    if bases_mask(after.values()) != mask_after:
        return None

    runs = int(row.get("runs_scored") or 0)
    outs_recorded = int(row.get("outs_after") or 0) - int(row.get("outs_before") or 0)
    if outs_recorded < 0:
        return None

    inning_ends = int(row.get("outs_before") or 0) + outs_recorded >= 3
    moves: list[tuple[str, str]] = []
    scored = 0
    retired = 0
    for runner_id, base in sorted(before.items(), key=lambda item: -item[1]):
        destination = after.get(runner_id)
        if destination is not None:
            moves.append((_INDEX_BASE[base], _INDEX_BASE[destination]))
        elif inning_ends and scored >= runs and retired >= outs_recorded:
            # The half-inning ended and this runner was stranded where they stood.
            moves.append((_INDEX_BASE[base], _INDEX_BASE[base]))
        elif scored < runs:
            moves.append((_INDEX_BASE[base], "HOME"))
            scored += 1
        else:
            moves.append((_INDEX_BASE[base], "OUT"))
            retired += 1

    batter_id = str(row.get("batter_id") or "")
    batter_destination = after.get(batter_id)
    if batter_destination is not None:
        moves.append(("BATTER_BOX", _INDEX_BASE[batter_destination]))
    elif scored < runs:
        moves.append(("BATTER_BOX", "HOME"))
        scored += 1
    elif retired < outs_recorded:
        moves.append(("BATTER_BOX", "OUT"))
        retired += 1
    elif inning_ends:
        moves.append(("BATTER_BOX", "FIRST"))
    else:
        return None

    if scored != runs or retired != outs_recorded:
        return None
    return tuple(moves)


def template_is_legal(
    template: Sequence[tuple[str, str]],
    *,
    mask_before: int,
    mask_after: int,
    runs: int,
    outs_added: int,
    outs_before: int = 0,
) -> bool:
    """Every conservation and ordering rule a movement template must satisfy.

    Two regimes, matching the accepted transition model's own legality rule:

    * The inning continues -- strict conservation. Ending occupancy must equal
      ``mask_after``, scored runners must equal ``runs`` and recorded outs must
      equal ``outs_added``.
    * The third out is recorded -- the half-inning ends, ``mask_after`` is 0 and
      every runner who was neither retired nor scored is STRANDED on the base
      they reached. Stranded runners are not outs and are not conserved into the
      next state, exactly as the transition model defines it.
    """

    inning_ends = outs_before + outs_added >= 3

    origins = [item[0] for item in template]
    if len(origins) != len(set(origins)):
        return False
    expected_origins = {_INDEX_BASE[base] for base in mask_bases(mask_before)} | {"BATTER_BOX"}
    if set(origins) != expected_origins:
        return False

    destinations = [item[1] for item in template if item[1] in _BASE_INDEX]
    if len(destinations) != len(set(destinations)):
        return False
    if sum(1 for item in template if item[1] == "HOME") != runs:
        return False
    if sum(1 for item in template if item[1] == "OUT") != outs_added:
        return False
    if inning_ends:
        if mask_after != 0:
            return False
    elif bases_mask(_BASE_INDEX[item] for item in destinations) != mask_after:
        return False

    # No runner may pass another: order on the bases must be preserved.
    ranked = [
        (0 if origin == "BATTER_BOX" else _BASE_INDEX[origin],
         4 if destination == "HOME" else _BASE_INDEX.get(destination))
        for origin, destination in template
        if destination != "OUT"
    ]
    ranked.sort()
    advanced = [destination for _, destination in ranked if destination is not None]
    if advanced != sorted(advanced):
        return False
    for origin, destination in ranked:
        if destination is not None and destination < origin:
            return False
    return True


def enumerate_legal_templates(
    *, mask_before: int, mask_after: int, runs: int, outs_added: int,
    outs_before: int = 0,
) -> tuple[tuple[tuple[str, str], ...], ...]:
    """Every legal explicit template compatible with one aggregate transition.

    The space is tiny -- at most three runners plus the batter, each with five
    possible destinations -- so it is enumerated exhaustively rather than
    approximated. Enumerating also makes the compatible set itself available,
    which is what the fitted sampler draws from.
    """

    origins = [_INDEX_BASE[base] for base in mask_bases(mask_before)] + ["BATTER_BOX"]
    destinations = ("FIRST", "SECOND", "THIRD", "HOME", "OUT")
    legal: list[tuple[tuple[str, str], ...]] = []
    for combination in itertools.product(destinations, repeat=len(origins)):
        template = tuple(zip(origins, combination))
        if template_is_legal(
            template, mask_before=mask_before, mask_after=mask_after,
            runs=runs, outs_added=outs_added, outs_before=outs_before,
        ):
            legal.append(template)
    return tuple(legal)


def _advancement(template: Sequence[tuple[str, str]]) -> int:
    total = 0
    for origin, destination in template:
        if destination == "OUT":
            continue
        start = 0 if origin == "BATTER_BOX" else _BASE_INDEX[origin]
        finish = 4 if destination == "HOME" else _BASE_INDEX[destination]
        total += max(finish - start, 0)
    return total


def legal_backoff_template(
    *, mask_before: int, mask_after: int, runs: int, outs_added: int,
    outs_before: int = 0,
) -> tuple[tuple[str, str], ...] | None:
    """The deterministic legal template used when no fitted template applies.

    Chooses the minimum-advancement legal assignment, tie-broken by a stable
    ordering, so the same aggregate transition always resolves identically.
    """

    legal = enumerate_legal_templates(
        mask_before=mask_before, mask_after=mask_after, runs=runs,
        outs_added=outs_added, outs_before=outs_before,
    )
    if not legal:
        return None
    return min(legal, key=lambda template: (_advancement(template), repr(template)))


# ---------------------------------------------------------------------------
# 4. Fitted conditional samplers
# ---------------------------------------------------------------------------

def _stable_hash(*parts: Any) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


@dataclass
class ConditionalSampler:
    """Weighted empirical sampler with an explicit backoff hierarchy.

    Every distribution is fitted inside one chronological fold. Sampling is a
    deterministic function of the supplied seed material, so a replay of the
    same trace reproduces the same draw exactly.
    """

    minimum_support: int = 25
    tables: dict[str, dict[tuple, Counter]] = field(default_factory=dict)

    def fit(self, level: str, key: tuple, value: Any) -> None:
        self.tables.setdefault(level, {}).setdefault(key, Counter())[value] += 1

    def support(self, level: str, key: tuple) -> int:
        return int(sum(self.tables.get(level, {}).get(key, Counter()).values()))

    def sample(
        self, hierarchy: Sequence[tuple[str, tuple]], *, seed: Any,
    ) -> tuple[Any | None, str, int]:
        """Draw from the most specific level with enough support.

        Returns ``(value, level_used, support)``. ``level_used`` is
        ``NO_SUPPORT`` when no level qualifies, which the caller must handle by
        falling back to a deterministic legal option and flagging it.
        """

        for level, key in hierarchy:
            counter = self.tables.get(level, {}).get(key)
            total = int(sum(counter.values())) if counter else 0
            if not counter or total < self.minimum_support:
                continue
            options = sorted(counter.items(), key=lambda item: (-item[1], repr(item[0])))
            draw = _stable_hash(seed, level, key) % total
            cumulative = 0
            for value, weight in options:
                cumulative += weight
                if draw < cumulative:
                    return value, level, total
        return None, "NO_SUPPORT", 0


#: Geometry backoff hierarchy, most specific first.
#:
#: Trajectory, zone and depth are drawn as ONE joint value, so conditioning on
#: batted-ball type would be circular. Handedness is absent from the registered
#: play_transition family and is therefore not a conditioning level here.
GEOMETRY_LEVELS = (
    "outcome_park",
    "outcome",
    "league_contact_prior",
)

RUNNER_LEVELS = (
    "outcome_state_outs_runs_after_bbtype",
    "outcome_state_outs_runs_after",
    "outcome_state_runs_after",
    "state_runs_after",
)


@dataclass
class PlayGeometryModel:
    """Fold-local fitted geometry and runner-movement distributions."""

    fold_id: str
    geometry: ConditionalSampler = field(default_factory=ConditionalSampler)
    runners: ConditionalSampler = field(default_factory=ConditionalSampler)
    rows_fitted: int = 0
    rows_with_location: int = 0
    rows_with_runner_template: int = 0
    seasons: tuple[int, ...] = ()

    # -- fitting ---------------------------------------------------------
    def fit_row(self, row: Mapping[str, Any]) -> None:
        outcome = row.get("pa_outcome")
        if not outcome:
            return
        self.rows_fitted += 1
        parsed = parse_event_text(row.get("event_text"))
        park = str(row.get("park_id") or "UNKNOWN_PARK")

        if parsed.contact and parsed.has_location and parsed.trajectory:
            self.rows_with_location += 1
            # The joint value keeps trajectory, zone and depth together, so a
            # drawn geometry is always a combination that actually occurred.
            value = (parsed.trajectory, parsed.zone, parsed.depth, parsed.foul)
            self.geometry.fit("outcome_park", (outcome, park), value)
            self.geometry.fit("outcome", (outcome,), value)
            self.geometry.fit("league_contact_prior", ("ANY_CONTACT",), value)

        template = observed_runner_template(row)
        if template is None:
            return
        mask_before = int(row.get("base_mask_before") or 0)
        mask_after = int(row.get("base_mask_after") or 0)
        runs = int(row.get("runs_scored") or 0)
        outs_added = int(row.get("outs_after") or 0) - int(row.get("outs_before") or 0)
        outs_before = int(row.get("outs_before") or 0)
        if not template_is_legal(
            template, mask_before=mask_before, mask_after=mask_after,
            runs=runs, outs_added=outs_added, outs_before=outs_before,
        ):
            return
        self.rows_with_runner_template += 1
        bbtype = parsed.trajectory or "NO_CONTACT"
        self.runners.fit(
            "outcome_state_outs_runs_after_bbtype",
            (outcome, mask_before, outs_before, runs, mask_after, outs_added, bbtype), template)
        self.runners.fit(
            "outcome_state_outs_runs_after",
            (outcome, mask_before, outs_before, runs, mask_after, outs_added), template)
        self.runners.fit(
            "outcome_state_runs_after",
            (outcome, mask_before, runs, mask_after, outs_added), template)
        self.runners.fit(
            "state_runs_after",
            (mask_before, runs, mask_after, outs_added), template)

    def fit(self, rows: Iterable[Mapping[str, Any]]) -> "PlayGeometryModel":
        for row in rows:
            self.fit_row(row)
        return self

    # -- sampling --------------------------------------------------------
    def sample_geometry(
        self, *, outcome: str, park: str, seed: Any,
    ) -> dict[str, Any]:
        """Geometry compatible with an already-decided outcome, or a null."""

        if outcome in {"STRIKEOUT", "WALK_HBP_CI", "WALK", "HIT_BY_PITCH"}:
            return {
                "contactOccurred": False,
                "battedBallType": None,
                "geometryAuthority": "NO_CONTACT",
                "geometryBackoffLevel": None,
                "point": None,
                **{name: None for name in UNSUPPORTED_GEOMETRY_FIELDS},
            }

        hierarchy: list[tuple[str, tuple]] = [
            ("outcome_park", (outcome, park)),
            ("outcome", (outcome,)),
            ("league_contact_prior", ("ANY_CONTACT",)),
        ]
        value, level, support = self.geometry.sample(hierarchy, seed=seed)

        if value is None:
            return {
                "contactOccurred": True,
                "battedBallType": None,
                "geometryAuthority": "UNLOCATED_CONTACT",
                "geometryBackoffLevel": "NO_SUPPORT",
                "point": None,
                **{name: None for name in UNSUPPORTED_GEOMETRY_FIELDS},
            }

        trajectory, zone, depth, foul = value
        point = zone_to_point(zone, depth)
        return {
            "contactOccurred": True,
            "battedBallType": trajectory,
            "locationZone": zone,
            "depthModifier": depth,
            "foulLocation": bool(foul),
            "geometryAuthority": "RETROSHEET_LOCATION_ZONE_CENTROID",
            "geometryBackoffLevel": level,
            "geometryBackoffSupport": support,
            "point": point,
            **{name: None for name in UNSUPPORTED_GEOMETRY_FIELDS},
        }

    def sample_runner_template(
        self,
        *,
        outcome: str,
        mask_before: int,
        outs_before: int,
        runs: int,
        mask_after: int,
        outs_added: int,
        batted_ball_type: str | None,
        seed: Any,
    ) -> tuple[tuple[tuple[str, str], ...], str, int]:
        """A legal explicit movement template for an already-decided play."""

        bbtype = batted_ball_type or "NO_CONTACT"
        hierarchy = [
            ("outcome_state_outs_runs_after_bbtype",
             (outcome, mask_before, outs_before, runs, mask_after, outs_added, bbtype)),
            ("outcome_state_outs_runs_after",
             (outcome, mask_before, outs_before, runs, mask_after, outs_added)),
            ("outcome_state_runs_after",
             (outcome, mask_before, runs, mask_after, outs_added)),
            ("state_runs_after", (mask_before, runs, mask_after, outs_added)),
        ]
        template, level, support = self.runners.sample(hierarchy, seed=seed)
        if template is not None and template_is_legal(
            template, mask_before=mask_before, mask_after=mask_after,
            runs=runs, outs_added=outs_added, outs_before=outs_before,
        ):
            return template, level, support

        backoff = legal_backoff_template(
            mask_before=mask_before, mask_after=mask_after,
            runs=runs, outs_added=outs_added, outs_before=outs_before,
        )
        if backoff is None:
            raise PlayGeometryError(
                "no legal runner template exists for "
                f"{outcome} {mask_before}->{mask_after} runs={runs} outs+={outs_added}"
            )
        return backoff, "DETERMINISTIC_LEGAL_BACKOFF", 0
