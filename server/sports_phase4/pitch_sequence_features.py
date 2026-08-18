"""MLB_PITCH_SEQUENCE_PROCESS_FEATURES_V1 — E1 free pitch-sequence parser + features.

A deterministic parser and leakage-safe process-feature engine over the governed
FD1 ``pitch_sequence`` family (Retrosheet play pitch-sequence notation,
``source_event_granularity = RETROSHEET_PLAY_PITCH_SEQUENCE_NOT_STATCAST_PITCH``).
This module fits **no model**, estimates nothing, and never infers velocity, pitch
type, spin, movement, location, target, catcher call, or any contact-quality /
tracking fact — the free encoding does not contain them.

Only categories whose semantics are reliably supported by the documented notation
are classified; every other symbol is counted explicitly as UNKNOWN (never silently
dropped). Count-state reconstruction (balls/strikes) is derived from the same
notation and is used only for two-strike / first-pitch descriptive rates.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

PARSER_VERSION = "MLB_PITCH_SEQUENCE_PARSER_V1"
FEATURE_CONTRACT_NAME = "MLB_PITCH_SEQUENCE_PROCESS_FEATURES_V1"
FEATURE_SCHEMA_VERSION = "MLB_PITCH_SEQUENCE_PROCESS_FEATURES_V1"

# Documented Retrosheet pitch-code semantics, mapped to the categories whose meaning
# is reliably supported. Confidence is recorded so the audit can be honest.
#   BALL          B ball, V automatic ball
#   CALLED_STRIKE C called strike, A automatic strike
#   SWINGING_STRIKE S swinging strike, M missed bunt, T foul tip (caught = strike)
#   FOUL          F foul, L foul bunt, O foul tip on bunt
#   IN_PLAY       X ball put into play by the batter
#   HIT_BY_PITCH  H hit batter
#   PITCHOUT      P pitchout (a delivered pitch; treated as a ball for count state)
PITCH_CATEGORY: dict[str, str] = {
    "B": "BALL", "V": "BALL",
    "C": "CALLED_STRIKE", "A": "CALLED_STRIKE",
    "S": "SWINGING_STRIKE", "M": "SWINGING_STRIKE", "T": "SWINGING_STRIKE",
    "F": "FOUL", "L": "FOUL", "O": "FOUL",
    "X": "IN_PLAY",
    "H": "HIT_BY_PITCH",
    "P": "PITCHOUT",
}
# Non-pitch markers: pickoff throws, runner-going / blocked-pitch modifiers, and
# non-batter play separators. These are NOT deliveries to the batter and never
# advance the count.
NON_PITCH_MARKERS: frozenset[str] = frozenset({".", ">", "*", "+", "1", "2", "3", "N", "R"})

# Categories that are "pitches to the batter" (denominator for pitch-level rates).
PITCH_CATEGORIES: tuple[str, ...] = (
    "BALL", "CALLED_STRIKE", "SWINGING_STRIKE", "FOUL", "IN_PLAY", "HIT_BY_PITCH", "PITCHOUT",
)
_BALL_LIKE = {"BALL", "PITCHOUT"}
_CALLED = {"CALLED_STRIKE"}
_SWING_MISS = {"SWINGING_STRIKE"}
_FOUL = {"FOUL"}


@dataclass(frozen=True)
class ParsedPlateAppearance:
    """Deterministic per-PA parse result. Pure counts; no inference."""

    pitches: int
    balls: int
    called_strikes: int
    swinging_strikes: int
    fouls: int
    in_play: int
    hit_by_pitch: int
    pitchouts: int
    unknown_tokens: int
    non_pitch_markers: int
    reached_two_strikes: bool
    first_pitch_strike: bool
    two_strike_pitches: int
    two_strike_swinging: int
    two_strike_foul: int
    two_strike_in_play: int
    terminal_category: str

    def as_row(self) -> dict[str, Any]:
        return {
            "pitches": self.pitches,
            "balls": self.balls,
            "called_strikes": self.called_strikes,
            "swinging_strikes": self.swinging_strikes,
            "fouls": self.fouls,
            "in_play": self.in_play,
            "hit_by_pitch": self.hit_by_pitch,
            "pitchouts": self.pitchouts,
            "unknown_tokens": self.unknown_tokens,
            "reached_two_strikes": int(self.reached_two_strikes),
            "first_pitch_strike": int(self.first_pitch_strike),
            "two_strike_pitches": self.two_strike_pitches,
            "two_strike_swinging": self.two_strike_swinging,
            "two_strike_foul": self.two_strike_foul,
            "two_strike_in_play": self.two_strike_in_play,
        }


def classify_symbol(symbol: str) -> str:
    """Return the governed category for one raw symbol (UNKNOWN / NON_PITCH otherwise)."""

    if symbol in PITCH_CATEGORY:
        return PITCH_CATEGORY[symbol]
    if symbol in NON_PITCH_MARKERS:
        return "NON_PITCH"
    return "UNKNOWN"


def parse_sequence(sequence: str | None) -> ParsedPlateAppearance:
    """Deterministically parse one Retrosheet pitch-sequence string.

    Non-pitch markers are skipped and never advance the count. Foul adds a strike
    only when strikes < 2. IN_PLAY / HIT_BY_PITCH are terminal. Unknown symbols are
    counted explicitly, never dropped silently.
    """

    balls = called = swinging = fouls = in_play = hbp = pitchouts = unknown = markers = 0
    strikes = 0
    reached_two = False
    first_pitch_strike = False
    seen_first_pitch = False
    two_pitches = two_swing = two_foul = two_inplay = 0
    terminal = "NONE"

    for symbol in str(sequence or ""):
        category = classify_symbol(symbol)
        if category == "NON_PITCH":
            markers += 1
            continue
        if category == "UNKNOWN":
            unknown += 1
            continue
        # This is a delivered pitch.
        at_two_strikes = strikes >= 2
        if at_two_strikes:
            two_pitches += 1
        if not seen_first_pitch:
            seen_first_pitch = True
            first_pitch_strike = category in {"CALLED_STRIKE", "SWINGING_STRIKE", "FOUL", "IN_PLAY"}

        if category == "BALL" or category == "PITCHOUT":
            balls += 1
            if category == "PITCHOUT":
                pitchouts += 1
            else:
                pass
        elif category == "CALLED_STRIKE":
            called += 1
            strikes = min(strikes + 1, 2)
        elif category == "SWINGING_STRIKE":
            swinging += 1
            if at_two_strikes:
                two_swing += 1
            strikes = min(strikes + 1, 2)
        elif category == "FOUL":
            fouls += 1
            if at_two_strikes:
                two_foul += 1
            if strikes < 2:
                strikes += 1
        elif category == "IN_PLAY":
            in_play += 1
            if at_two_strikes:
                two_inplay += 1
            terminal = "IN_PLAY"
        elif category == "HIT_BY_PITCH":
            hbp += 1
            terminal = "HIT_BY_PITCH"
        if strikes >= 2:
            reached_two = True
        if terminal != "NONE":
            break

    pitches = balls + called + swinging + fouls + in_play + hbp
    # (pitchouts are already inside `balls`; do not double count.)
    if terminal == "NONE" and pitches:
        terminal = "OTHER"
    return ParsedPlateAppearance(
        pitches=pitches,
        balls=balls,
        called_strikes=called,
        swinging_strikes=swinging,
        fouls=fouls,
        in_play=in_play,
        hit_by_pitch=hbp,
        pitchouts=pitchouts,
        unknown_tokens=unknown,
        non_pitch_markers=markers,
        reached_two_strikes=reached_two,
        first_pitch_strike=first_pitch_strike,
        two_strike_pitches=two_pitches,
        two_strike_swinging=two_swing,
        two_strike_foul=two_foul,
        two_strike_in_play=two_inplay,
        terminal_category=terminal,
    )


def parse_quality(sequences: Iterable[str | None]) -> dict[str, Any]:
    """Aggregate parse-quality evidence over a set of raw sequences."""

    from collections import Counter

    total_rows = non_empty = empty_rows = 0
    total_symbols = classified = unknown = 0
    rows_with_unknown = fully_unusable = 0
    unknown_symbols: Counter[str] = Counter()
    for raw in sequences:
        total_rows += 1
        text = str(raw or "")
        if not text:
            empty_rows += 1
            fully_unusable += 1
            continue
        non_empty += 1
        row_unknown = 0
        row_classified = 0
        for symbol in text:
            total_symbols += 1
            category = classify_symbol(symbol)
            if category == "UNKNOWN":
                unknown += 1
                row_unknown += 1
                unknown_symbols[symbol] += 1
            else:
                classified += 1
                if category != "NON_PITCH":
                    row_classified += 1
        if row_unknown:
            rows_with_unknown += 1
        if row_classified == 0:
            fully_unusable += 1
    return {
        "totalRows": total_rows,
        "nonEmptySequenceRows": non_empty,
        "emptySequenceRows": empty_rows,
        "totalSymbols": total_symbols,
        "classifiedSymbols": classified,
        "unknownSymbols": unknown,
        "parseSuccessRate": (classified / total_symbols) if total_symbols else None,
        "rowsWithAnyUnknown": rows_with_unknown,
        "fullyUnusableRows": fully_unusable,
        "topUnknownSymbols": [{"symbol": s, "count": c} for s, c in unknown_symbols.most_common(10)],
    }


def parser_category_table() -> list[dict[str, str]]:
    """The governed classification table (for the contract/registry/UI)."""

    rows = [
        {"symbol": symbol, "category": category, "support": "SUPPORTED"}
        for symbol, category in sorted(PITCH_CATEGORY.items())
    ]
    rows.extend({"symbol": m, "category": "NON_PITCH", "support": "SUPPORTED"} for m in sorted(NON_PITCH_MARKERS))
    return rows


def readiness_from_quality(quality: Mapping[str, Any]) -> str:
    """PITCH_SEQUENCE_READY / PARTIALLY_READY / BLOCKED from measured parse quality."""

    rate = quality.get("parseSuccessRate") or 0.0
    non_empty = quality.get("nonEmptySequenceRows") or 0
    total = quality.get("totalRows") or 1
    coverage = non_empty / total
    if rate >= 0.995 and coverage >= 0.98:
        return "PITCH_SEQUENCE_READY"
    if rate >= 0.95 and coverage >= 0.90:
        return "PITCH_SEQUENCE_PARTIALLY_READY"
    return "PITCH_SEQUENCE_BLOCKED"


__all__ = [
    "FEATURE_CONTRACT_NAME",
    "FEATURE_SCHEMA_VERSION",
    "NON_PITCH_MARKERS",
    "PARSER_VERSION",
    "PITCH_CATEGORY",
    "PITCH_CATEGORIES",
    "ParsedPlateAppearance",
    "classify_symbol",
    "parse_quality",
    "parse_sequence",
    "parser_category_table",
    "readiness_from_quality",
]
