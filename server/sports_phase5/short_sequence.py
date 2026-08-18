"""Bounded short-sequence stochastic integration (Phase 5C, gate validation only).

Composes the four proven/loaded seams — historical participants, the D3 probabilistic PA
provider, the Phase 5B base-out transition model, and the deterministic Phase 5A kernel —
over a BOUNDED sequence of plate appearances (25-100), NOT whole games and NOT forecasts.

Its only purpose is to prove the interfaces integrate cleanly and legally: every D3 vector is
valid, every sampled class is legal, every sampled transition is legal for the state, runner
identities apply forward without duplication/loss, the next batter and active pitcher are
resolved, innings progress, and nothing corrupts state. It records lightweight simulation
event records and is fully reproducible under a seed lineage.

No whole-game Monte Carlo, no win/run-line/total probabilities, no betting logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

import numpy as np

from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5.game_initialization import RngLineage, SimulationEventRecord
from server.sports_phase5.game_replay import GameState
from server.sports_phase5.pa_provider import (
    D3ProbabilisticPAProvider,
    PAInvocationContext,
    PAProviderError,
)

CLASS_INDEX = {name: i for i, name in enumerate(bt.PA_CLASSES)}


class ShortSequenceError(RuntimeError):
    """Structural fault in the bounded integration (never used to hide a legality defect)."""


@dataclass(frozen=True)
class TeamLineup:
    team_id: str
    batting_order: tuple[str, ...]        # retrosheet ids, slot order (length 9)
    starting_pitcher: str                  # retrosheet id
    uuid_of: Mapping[str, str]             # retrosheet id -> canonical uuid (batters+pitcher)


@dataclass
class _HalfState:
    slot_index: int = 0  # next batter slot for this team


@dataclass(frozen=True)
class ShortSequenceResult:
    simulation_id: str
    pa_count: int
    events: tuple[SimulationEventRecord, ...]
    illegal_transitions: int
    invalid_probability_vectors: int
    duplicated_runners: int
    lost_runners: int
    unresolved_batters: int
    unresolved_pitchers: int
    inning_progression_ok: bool
    outcome_class_counts: Mapping[str, int]

    def clean(self) -> bool:
        return (
            self.illegal_transitions == 0
            and self.invalid_probability_vectors == 0
            and self.duplicated_runners == 0
            and self.lost_runners == 0
            and self.unresolved_batters == 0
            and self.unresolved_pitchers == 0
            and self.inning_progression_ok
        )

    def public(self) -> dict[str, Any]:
        return {
            "simulationId": self.simulation_id,
            "paCount": self.pa_count,
            "illegalTransitions": self.illegal_transitions,
            "invalidProbabilityVectors": self.invalid_probability_vectors,
            "duplicatedRunners": self.duplicated_runners,
            "lostRunners": self.lost_runners,
            "unresolvedBatters": self.unresolved_batters,
            "unresolvedPitchers": self.unresolved_pitchers,
            "inningProgressionOk": self.inning_progression_ok,
            "outcomeClassCounts": dict(self.outcome_class_counts),
            "clean": self.clean(),
        }


def _base_mask_to_runners(base_mask: int, occupants: Mapping[int, str]) -> dict[int, str]:
    # apply_transition_to_runners keys runners by base POSITION (1,2,3): pos p occupies bit
    # 1<<(p-1). occupants is carried forward keyed by position.
    return {pos: occupants[pos] for pos in (1, 2, 3) if base_mask & (1 << (pos - 1))}


def _half_transition(state: GameState) -> GameState:
    if state.top:
        return replace(state, top=False, outs=0, base_mask=0)
    return replace(state, inning=state.inning + 1, top=True, outs=0, base_mask=0)


def run_short_sequence(
    *,
    provider: D3ProbabilisticPAProvider,
    transition_model: bt.TransitionModel,
    away: TeamLineup,
    home: TeamLineup,
    game_id: str,
    game_date: str,
    season: int,
    rng_lineage: RngLineage,
    max_pas: int,
    transition_authority: str,
) -> ShortSequenceResult:
    """Run a bounded stochastic sequence of ``max_pas`` PAs and validate legality throughout."""

    if not (1 <= max_pas <= 200):
        raise ShortSequenceError("bounded sequence length must be in [1, 200]")
    pa_rng = rng_lineage.pa_rng()
    tr_rng = rng_lineage.transition_rng()
    simulation_id = f"shortseq:{game_id}:{rng_lineage.master_seed}"

    state = GameState(inning=1, top=True, outs=0, base_mask=0, away_score=0, home_score=0)
    half = {True: _HalfState(), False: _HalfState()}  # keyed by 'top' → offense team pointer
    # 'top' half => away bats; 'bottom' => home bats
    offense_lineup = {True: away, False: home}
    defense_lineup = {True: home, False: away}
    # Persistent runner identity occupants by base bit.
    occupants: dict[int, str] = {}

    events: list[SimulationEventRecord] = []
    illegal = invalid = dup = lost = unresolved_b = unresolved_p = 0
    outcome_counts: dict[str, int] = {c: 0 for c in bt.PA_CLASSES}
    inning_ok = True
    last_inning_half = (1, True)
    pa_counter = 0

    for pa_index in range(max_pas):
        batting = offense_lineup[state.top]
        fielding = defense_lineup[state.top]
        team_ptr = half[state.top]
        batter_ret = batting.batting_order[team_ptr.slot_index % len(batting.batting_order)]
        pitcher_ret = fielding.starting_pitcher
        batter_uuid = batting.uuid_of.get(batter_ret)
        pitcher_uuid = fielding.uuid_of.get(pitcher_ret)
        if batter_uuid is None:
            unresolved_b += 1
            break
        if pitcher_uuid is None:
            unresolved_p += 1
            break

        score_diff = (
            state.away_score - state.home_score
            if state.top
            else state.home_score - state.away_score
        )
        context = PAInvocationContext(
            game_id=game_id, game_date=game_date, season=season,
            inning=state.inning, top=state.top, outs_before=state.outs,
            base_mask_before=state.base_mask, batting_score_diff_before=score_diff,
            batter_uuid=batter_uuid, pitcher_uuid=pitcher_uuid,
        )
        try:
            response = provider.score(context)
        except PAProviderError:
            invalid += 1
            break
        if not response.valid:
            invalid += 1
            break
        # Sample PA class from the D3 vector.
        cls_idx = int(pa_rng.choice(len(bt.PA_CLASSES), p=np.asarray(response.probabilities)))
        pa_class = bt.PA_CLASSES[cls_idx]
        outcome_counts[pa_class] += 1

        # Sample a legal transition and validate legality against the state.
        transition = transition_model.sample(pa_class, state.outs, state.base_mask, tr_rng)
        if not bt.is_legal(state.outs, state.base_mask, transition):
            illegal += 1
            break

        # Apply runner identities forward.
        runner_ids = _base_mask_to_runners(state.base_mask, occupants)
        applied = bt.apply_transition_to_runners(state.base_mask, runner_ids, batter_ret, transition)
        outs_added, base_mask_after, runs = transition
        # Duplicate/lost runner accounting: incoming runners + batter == out + scored + stranded + remaining.
        after_runners: Mapping[int, str] = applied["afterRunners"]
        scored_list = list(applied["scored"])
        stranded_list = list(applied["stranded"])
        incoming = set(runner_ids.values()) | {batter_ret}
        on_base = list(after_runners.values())
        # No identity may appear twice on base.
        if len(set(on_base)) != len(on_base):
            dup += 1
        # Conservation of identities: on base + scored + stranded + put out == incoming.
        accounted = len(set(on_base)) + len(scored_list) + len(stranded_list) + int(outs_added)
        if accounted != len(incoming):
            lost += 1

        outs_after = state.outs + outs_added
        # Update score to the batting team.
        away_score = state.away_score + (runs if state.top else 0)
        home_score = state.home_score + (0 if state.top else runs)

        events.append(
            SimulationEventRecord(
                simulation_id=simulation_id, game_id=game_id, pa_index=pa_index,
                inning=state.inning, top=state.top, outs_before=state.outs,
                base_mask_before=state.base_mask, batter_id=batter_ret, pitcher_id=pitcher_ret,
                pa_probability_authority=response.model_authority, sampled_pa_class=pa_class,
                transition_model_authority=transition_authority, sampled_transition=transition,
                runs_scored=int(runs), outs_after=outs_after, base_mask_after=base_mask_after,
                rng_master_seed=rng_lineage.master_seed, rng_game_key=rng_lineage.game_key,
            )
        )
        pa_counter += 1
        team_ptr.slot_index += 1

        # Advance kernel state.
        if outs_after >= 3:
            occupants = {}
            state = replace(state, outs=3, base_mask=0, away_score=away_score, home_score=home_score)
            new_state = _half_transition(state)
            # inning must move forward or half must flip
            if not (
                (new_state.inning, new_state.top) != (state.inning, state.top)
            ):
                inning_ok = False
            state = new_state
        else:
            occupants = dict(after_runners)
            state = replace(
                state, outs=outs_after, base_mask=base_mask_after,
                away_score=away_score, home_score=home_score,
            )
        # Monotonic (inning, half) progression check.
        cur = (state.inning, 0 if state.top else 1)
        prev = (last_inning_half[0], 0 if last_inning_half[1] else 1)
        if cur < prev:
            inning_ok = False
        last_inning_half = (state.inning, state.top)

    return ShortSequenceResult(
        simulation_id=simulation_id,
        pa_count=pa_counter,
        events=tuple(events),
        illegal_transitions=illegal,
        invalid_probability_vectors=invalid,
        duplicated_runners=dup,
        lost_runners=lost,
        unresolved_batters=unresolved_b,
        unresolved_pitchers=unresolved_p,
        inning_progression_ok=inning_ok,
        outcome_class_counts=outcome_counts,
    )


__all__ = [
    "ShortSequenceError",
    "TeamLineup",
    "ShortSequenceResult",
    "run_short_sequence",
]
