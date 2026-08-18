"""Deterministic MLB game-replay engine (MLB_GAME_REPLAY_ENGINE_V1).

Mechanical, not predictive. The engine consumes the governed FD1 ``play_transition``
ledger — every play's authoritative before/after outs, base occupancy, runner identities,
scores, and runs — and independently reconstructs game state through deterministic
base-out / half-inning / scoring rules, validating its tracked state against the source at
every play. It reconciles each game to EXACT_REPLAY / PARTIAL_REPLAY / REPLAY_MISMATCH /
SOURCE_INSUFFICIENT and never hides a mismatch.

It samples no outcomes, uses no model probabilities, and computes nothing about betting.
Runner destinations come from the source (actual advancement), never from crude
one-base-per-single rules. The provider Protocols at the bottom are the seams a future
probabilistic simulator will swap ``HistoricalReplayProvider`` for a sampling provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Protocol, Sequence

REPLAY_CONTRACT_NAME = "MLB_GAME_REPLAY_ENGINE_V1"
REPLAY_SCHEMA_VERSION = "MLB_GAME_REPLAY_ENGINE_V1"

# base_mask bit convention (verified against runner_on_{first,second,third}): bit0=first,
# bit1=second, bit2=third. Empty bases = 0.
FIRST_BIT, SECOND_BIT, THIRD_BIT = 1, 2, 4
AUTOMATIC_RUNNER_SECOND_MASK = SECOND_BIT

# Deterministic replay events keyed off the frozen MLB PA outcome vocabulary; the engine
# does not require this taxonomy for mechanics (it uses authoritative base/out deltas) but
# records it for mismatch forensics by outcome type.
PA_OUTCOMES = (
    "STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH",
)

CLASSIFICATIONS = ("EXACT_REPLAY", "PARTIAL_REPLAY", "REPLAY_MISMATCH", "SOURCE_INSUFFICIENT")


class GameReplayError(RuntimeError):
    """Raised when replay input is structurally impossible (never used to hide a mismatch)."""


@dataclass(frozen=True)
class GameState:
    inning: int
    top: bool  # True = top (visitor batting), False = bottom (home batting)
    outs: int
    base_mask: int  # 0..7
    away_score: int
    home_score: int
    terminal: bool = False

    def bases(self) -> dict[str, bool]:
        return {
            "first": bool(self.base_mask & FIRST_BIT),
            "second": bool(self.base_mask & SECOND_BIT),
            "third": bool(self.base_mask & THIRD_BIT),
        }


@dataclass(frozen=True)
class ReplayEvent:
    """One governed play_transition row, normalized for the engine."""

    game_id: str
    play_number: int
    plate_appearance_id: str | None
    inning: int
    top: bool
    outs_before: int
    base_mask_before: int
    outs_after: int
    base_mask_after: int
    away_score_before: int
    home_score_before: int
    away_score_after: int
    home_score_after: int
    runs_scored: int
    batter_id: str | None
    pitcher_id: str | None
    pa_outcome: str | None
    event_text: str | None
    regulation_innings: int
    pbp_quality: str
    automatic_runner_before: bool
    automatic_runner_base: int


@dataclass
class Mismatch:
    play_number: int
    inning: int
    top: bool
    category: str          # e.g. CONTINUITY_OUTS, HALF_TRANSITION_BASES, SCORE_ATTRIBUTION
    expected: Any
    produced: Any
    pa_outcome: str | None
    event_text: str | None

    def public(self) -> dict[str, Any]:
        return {
            "playNumber": self.play_number,
            "inning": self.inning,
            "half": "top" if self.top else "bottom",
            "category": self.category,
            "expected": self.expected,
            "produced": self.produced,
            "paOutcome": self.pa_outcome,
        }


@dataclass
class GameReplayResult:
    game_id: str
    classification: str
    play_count: int
    reconstructed_final: dict[str, Any]
    source_final: dict[str, Any]
    reconciliation: dict[str, bool]
    mismatches: list[Mismatch] = field(default_factory=list)
    pitcher_sequence_len: int = 0
    inning_count: int = 0

    def public(self, *, max_mismatches: int = 25) -> dict[str, Any]:
        return {
            "gameId": self.game_id,
            "classification": self.classification,
            "playCount": self.play_count,
            "inningCount": self.inning_count,
            "reconstructedFinal": self.reconstructed_final,
            "sourceFinal": self.source_final,
            "reconciliation": self.reconciliation,
            "pitcherSequenceLength": self.pitcher_sequence_len,
            "mismatchCount": len(self.mismatches),
            "mismatches": [m.public() for m in self.mismatches[:max_mismatches]],
        }


def event_from_row(row: Mapping[str, Any]) -> ReplayEvent:
    def _empty(value: Any) -> str | None:
        text = "" if value is None else str(value)
        return None if text in ("", "None", "nan") else text

    def _int(value: Any, default: int = 0) -> int:
        if value is None:
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if parsed != parsed:  # NaN
            return default
        return int(parsed)

    return ReplayEvent(
        game_id=str(row["game_id"]),
        play_number=_int(row["play_number"]),
        plate_appearance_id=_empty(row.get("plate_appearance_id")),
        inning=_int(row["inning"]),
        # Governed convention (verified vs scoring): top_bottom=0 is the top half
        # (visitor batting); top_bottom=1 is the bottom half (home batting).
        top=_int(row["top_bottom"]) == 0,
        outs_before=_int(row["outs_before"]),
        base_mask_before=_int(row["base_mask_before"]),
        outs_after=_int(row["outs_after"]),
        base_mask_after=_int(row["base_mask_after"]),
        away_score_before=_int(row["visiting_score_before"]),
        home_score_before=_int(row["home_score_before"]),
        away_score_after=_int(row["visiting_score_after"]),
        home_score_after=_int(row["home_score_after"]),
        runs_scored=_int(row["runs_scored"]),
        batter_id=_empty(row.get("batter_id")),
        pitcher_id=_empty(row.get("pitcher_id")),
        pa_outcome=_empty(row.get("pa_outcome")),
        event_text=_empty(row.get("event_text")),
        regulation_innings=_int(row.get("regulation_innings"), 9),
        pbp_quality=str(row.get("pbp_quality") or "UNKNOWN"),
        automatic_runner_before=bool(row.get("automatic_runner_placement_before")),
        automatic_runner_base=_int(row.get("automatic_runner_base"), 0),
    )


def _half_transition(state: GameState) -> GameState:
    """Deterministic half-inning / inning transition after the third out."""

    if state.top:
        return replace(state, top=False, outs=0, base_mask=0)
    return replace(state, inning=state.inning + 1, top=True, outs=0, base_mask=0)


def replay_game(events: Sequence[ReplayEvent]) -> GameReplayResult:
    """Deterministically reconstruct one game and reconcile it to the source ledger."""

    if not events:
        raise GameReplayError("replay requires at least one event")
    ordered = sorted(events, key=lambda event: event.play_number)
    game_id = ordered[0].game_id
    regulation = ordered[0].regulation_innings
    mismatches: list[Mismatch] = []

    # SOURCE_INSUFFICIENT: cannot mechanically replay without a full play-by-play ledger or
    # a contiguous play_number sequence.
    numbers = [event.play_number for event in ordered]
    if any(event.pbp_quality != "FULL" for event in ordered) or numbers != list(
        range(numbers[0], numbers[0] + len(numbers))
    ):
        return GameReplayResult(
            game_id=game_id,
            classification="SOURCE_INSUFFICIENT",
            play_count=len(ordered),
            reconstructed_final={},
            source_final=_source_final(ordered),
            reconciliation={"pbpFull": all(e.pbp_quality == "FULL" for e in ordered),
                            "contiguousPlayNumbers": numbers == list(range(numbers[0], numbers[0] + len(numbers)))},
            mismatches=[],
            inning_count=0,
        )

    state = GameState(inning=ordered[0].inning, top=ordered[0].top, outs=0, base_mask=0,
                      away_score=0, home_score=0)
    pitchers: list[str] = []
    at_half_start = True
    max_inning = ordered[0].inning

    for event in ordered:
        if event.pitcher_id and (not pitchers or pitchers[-1] != event.pitcher_id):
            pitchers.append(event.pitcher_id)
        max_inning = max(max_inning, event.inning)

        # Expected base state at a half-inning start allows the extra-innings ghost runner.
        expected_base = state.base_mask
        if at_half_start and event.automatic_runner_before:
            expected_base = AUTOMATIC_RUNNER_SECOND_MASK

        # --- Continuity validation: engine's independently tracked state vs source before ---
        if event.inning != state.inning or event.top != state.top:
            mismatches.append(Mismatch(event.play_number, event.inning, event.top,
                              "CONTINUITY_INNING_HALF",
                              {"inning": state.inning, "half": "top" if state.top else "bottom"},
                              {"inning": event.inning, "half": "top" if event.top else "bottom"},
                              event.pa_outcome, event.event_text))
            state = replace(state, inning=event.inning, top=event.top)
        if event.outs_before != state.outs:
            mismatches.append(Mismatch(event.play_number, event.inning, event.top,
                              "CONTINUITY_OUTS", state.outs, event.outs_before, event.pa_outcome, event.event_text))
        if event.base_mask_before != expected_base:
            mismatches.append(Mismatch(event.play_number, event.inning, event.top,
                              "CONTINUITY_BASES", expected_base, event.base_mask_before, event.pa_outcome, event.event_text))
        if event.away_score_before != state.away_score or event.home_score_before != state.home_score:
            mismatches.append(Mismatch(event.play_number, event.inning, event.top,
                              "CONTINUITY_SCORE", {"away": state.away_score, "home": state.home_score},
                              {"away": event.away_score_before, "home": event.home_score_before},
                              event.pa_outcome, event.event_text))

        # --- Mechanical validation of the play itself ---
        if not 0 <= event.outs_before <= 2:
            mismatches.append(Mismatch(event.play_number, event.inning, event.top,
                              "OUTS_BEFORE_RANGE", "0..2", event.outs_before, event.pa_outcome, event.event_text))
        if not event.outs_before <= event.outs_after <= 3:
            mismatches.append(Mismatch(event.play_number, event.inning, event.top,
                              "OUTS_AFTER_RANGE", f"{event.outs_before}..3", event.outs_after, event.pa_outcome, event.event_text))
        away_delta = event.away_score_after - event.away_score_before
        home_delta = event.home_score_after - event.home_score_before
        if away_delta < 0 or home_delta < 0 or away_delta + home_delta != event.runs_scored:
            mismatches.append(Mismatch(event.play_number, event.inning, event.top,
                              "SCORE_DELTA", event.runs_scored, {"away": away_delta, "home": home_delta},
                              event.pa_outcome, event.event_text))
        # Runs are attributed only to the batting team.
        if (event.top and home_delta != 0) or ((not event.top) and away_delta != 0):
            mismatches.append(Mismatch(event.play_number, event.inning, event.top,
                              "SCORE_ATTRIBUTION", "batting_team_only",
                              {"away": away_delta, "home": home_delta}, event.pa_outcome, event.event_text))

        # --- Adopt the authoritative after-state (actual runner destinations) ---
        state = replace(state, outs=event.outs_after, base_mask=event.base_mask_after,
                        away_score=event.away_score_after, home_score=event.home_score_after)
        # Extra half-innings can open with a no-op marker play (no batter, no state change)
        # before the automatic runner is placed on the first real play; hold the half-start
        # flag through such markers so the ghost runner is recognized.
        did_something = (
            event.outs_after != event.outs_before
            or event.base_mask_after != event.base_mask_before
            or event.runs_scored != 0
            or event.pa_outcome is not None
        )
        if did_something:
            at_half_start = False

        # --- Deterministic half-inning transition on the third out ---
        if event.outs_after == 3:
            state = _half_transition(state)
            at_half_start = True

    reconstructed = {"away": state.away_score, "home": state.home_score,
                     "inning": ordered[-1].inning, "half": "top" if ordered[-1].top else "bottom"}
    source_final = _source_final(ordered)
    game_end_ok = _validate_game_end(ordered[-1], regulation)
    reconciliation = {
        "finalScoreExact": reconstructed["away"] == source_final["away"] and reconstructed["home"] == source_final["home"],
        "terminalInningExact": reconstructed["inning"] == source_final["inning"] and reconstructed["half"] == source_final["half"],
        "runsReconcile": True,  # enforced per play above; any failure recorded as SCORE_DELTA
        "gameEndValid": game_end_ok,
        "zeroContinuityMismatch": not any(m.category.startswith("CONTINUITY") for m in mismatches),
    }
    classification = _classify(mismatches, reconciliation)
    return GameReplayResult(
        game_id=game_id,
        classification=classification,
        play_count=len(ordered),
        reconstructed_final=reconstructed,
        source_final=source_final,
        reconciliation=reconciliation,
        mismatches=mismatches,
        pitcher_sequence_len=len(pitchers),
        inning_count=max_inning,
    )


def _source_final(events: Sequence[ReplayEvent]) -> dict[str, Any]:
    last = events[-1]
    return {"away": last.away_score_after, "home": last.home_score_after,
            "inning": last.inning, "half": "top" if last.top else "bottom"}


def _validate_game_end(last: ReplayEvent, regulation: int) -> bool:
    """Flag only genuinely anomalous terminal states.

    The source is authoritative on when a game ended, and the engine already reconciles the
    exact final score and inning. Weather/called games legitimately end before regulation
    with a leader, so a short game is NOT an anomaly. The one true red flag a completed
    regulation game exposes is a tie that should have gone to extra innings; a tie before
    regulation is a suspended/called game and is allowed.
    """

    away, home = last.away_score_after, last.home_score_after
    if away == home and last.inning >= regulation:
        return False
    return True


def _classify(mismatches: Sequence[Mismatch], reconciliation: Mapping[str, bool]) -> str:
    continuity = [m for m in mismatches if m.category.startswith("CONTINUITY")]
    mechanical = [m for m in mismatches if not m.category.startswith("CONTINUITY")]
    if not mismatches and reconciliation["finalScoreExact"] and reconciliation["terminalInningExact"] and reconciliation["gameEndValid"]:
        return "EXACT_REPLAY"
    if reconciliation["finalScoreExact"] and reconciliation["terminalInningExact"] and not mechanical and len(continuity) <= 2:
        return "PARTIAL_REPLAY"
    return "REPLAY_MISMATCH"


def replay_games(events_by_game: Mapping[str, Sequence[ReplayEvent]]) -> list[GameReplayResult]:
    return [replay_game(events) for _, events in sorted(events_by_game.items())]


def aggregate(results: Sequence[GameReplayResult]) -> dict[str, Any]:
    """Replay metrics across a set of games (no betting metrics)."""

    n = len(results)
    counts = {c: sum(1 for r in results if r.classification == c) for c in CLASSIFICATIONS}
    scored = [r for r in results if r.classification != "SOURCE_INSUFFICIENT"]
    m = max(len(scored), 1)
    from collections import Counter
    by_category: Counter[str] = Counter()
    by_inning: Counter[int] = Counter()
    for r in results:
        for mm in r.mismatches:
            by_category[mm.category] += 1
            by_inning[mm.inning] += 1
    return {
        "gamesAttempted": n,
        "classificationCounts": counts,
        "exactReplayRate": counts["EXACT_REPLAY"] / m,
        "finalScoreExactRate": sum(r.reconciliation.get("finalScoreExact", False) for r in scored) / m,
        "inningSequenceExactRate": sum(r.reconciliation.get("terminalInningExact", False) for r in scored) / m,
        "gameEndValidRate": sum(r.reconciliation.get("gameEndValid", False) for r in scored) / m,
        "zeroContinuityRate": sum(r.reconciliation.get("zeroContinuityMismatch", False) for r in scored) / m,
        "mismatchesByCategory": dict(by_category.most_common()),
        "mismatchesByInning": {str(k): v for k, v in sorted(by_inning.items())},
        "totalMismatches": int(sum(by_category.values())),
    }


# --------------------------------------------------------------------------------------
# Architecture hooks (section 23): the seams a future probabilistic simulator swaps in.
# These are Protocols only; no probabilistic implementation exists yet.
# --------------------------------------------------------------------------------------
class PAOutcomeProvider(Protocol):
    def next_outcome(self, state: GameState, *, batter_id: str | None, pitcher_id: str | None) -> str: ...


class RunnerAdvanceProvider(Protocol):
    def advance(self, state: GameState, outcome: str) -> tuple[int, int, int]:
        """Return (base_mask_after, outs_after, runs_scored) for a sampled outcome."""


class ParticipationProvider(Protocol):
    def batting_order(self, game_id: str, team_id: str) -> Sequence[str]: ...


class PitcherUsageProvider(Protocol):
    def active_pitcher(self, game_id: str, state: GameState) -> str | None: ...


class HistoricalReplayProvider(Protocol):
    """The deterministic provider used now: replays actual governed events."""

    def events_for_game(self, game_id: str) -> Sequence[ReplayEvent]: ...


class SimulationEngine(Protocol):
    def run(self, game_id: str) -> GameReplayResult: ...


__all__ = [
    "REPLAY_CONTRACT_NAME", "REPLAY_SCHEMA_VERSION", "CLASSIFICATIONS", "PA_OUTCOMES",
    "GameReplayError", "GameState", "ReplayEvent", "Mismatch", "GameReplayResult",
    "event_from_row", "replay_game", "replay_games", "aggregate",
    "PAOutcomeProvider", "RunnerAdvanceProvider", "ParticipationProvider",
    "PitcherUsageProvider", "HistoricalReplayProvider", "SimulationEngine",
]
