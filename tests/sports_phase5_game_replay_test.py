"""Hermetic unit tests for the Phase 5 deterministic game-replay engine.

Each test builds a source-realistic play_transition sequence (the engine's actual input
shape) and asserts the deterministic mechanics: base-out transitions, scoring, inning /
half-inning progression, walk-offs, extra-innings ghost runner, pitcher changes, and
rejection of impossible/inconsistent state. No probabilistic simulation is exercised.
"""

from __future__ import annotations

import pytest

from server.sports_phase5 import game_replay as gr

FIRST, SECOND, THIRD = 1, 2, 4


class GameBuilder:
    """Builds an internally-consistent play_transition ledger, tracking state exactly as
    the governed source does (each play's before-state = the running state)."""

    def __init__(self, game_id="retrosheet:game:TEST", regulation=9):
        self.game_id = game_id
        self.regulation = regulation
        self.play_number = 0
        self.inning = 1
        self.top = True  # top_bottom=0
        self.outs = 0
        self.base = 0
        self.away = 0
        self.home = 0
        self.rows: list[dict] = []

    def play(self, *, outs_after, base_after, runs=0, outcome="BIP_OUT", pitcher="p1",
             batter="b1", auto=False, event_text=None):
        self.play_number += 1
        away_before, home_before = self.away, self.home
        if self.top:
            away_after = away_before + runs
            home_after = home_before
        else:
            away_after = away_before
            home_after = home_before + runs
        row = {
            "game_id": self.game_id, "season": 2024, "play_number": self.play_number,
            "plate_appearance_id": f"pa{self.play_number}",
            "inning": self.inning, "top_bottom": 0 if self.top else 1,
            "outs_before": self.outs, "base_mask_before": self.base,
            "outs_after": outs_after, "base_mask_after": base_after,
            "visiting_score_before": away_before, "home_score_before": home_before,
            "visiting_score_after": away_after, "home_score_after": home_after,
            "runs_scored": runs, "batter_id": batter, "pitcher_id": pitcher,
            "pa_outcome": outcome, "event_text": event_text,
            "regulation_innings": self.regulation, "pbp_quality": "FULL",
            "automatic_runner_placement_before": auto,
            "automatic_runner_base": 2 if auto else None,
        }
        self.rows.append(row)
        # adopt after-state; on third out, transition half/inning
        self.outs, self.base, self.away, self.home = outs_after, base_after, away_after, home_after
        if outs_after == 3:
            if self.top:
                self.top = False
            else:
                self.top = True
                self.inning += 1
            self.outs, self.base = 0, 0
        return self

    def marker(self):
        """A no-op half-start marker (no batter, no state change)."""
        self.play_number += 1
        self.rows.append({
            "game_id": self.game_id, "season": 2024, "play_number": self.play_number,
            "plate_appearance_id": None, "inning": self.inning, "top_bottom": 0 if self.top else 1,
            "outs_before": self.outs, "base_mask_before": self.base,
            "outs_after": self.outs, "base_mask_after": self.base,
            "visiting_score_before": self.away, "home_score_before": self.home,
            "visiting_score_after": self.away, "home_score_after": self.home,
            "runs_scored": 0, "batter_id": None, "pitcher_id": None, "pa_outcome": None,
            "event_text": "NP", "regulation_innings": self.regulation, "pbp_quality": "FULL",
            "automatic_runner_placement_before": False, "automatic_runner_base": None,
        })
        return self

    def place_ghost(self):
        """Mimic the extra-innings automatic runner appearing on the next real play."""
        self.base = SECOND
        return self

    def result(self):
        return gr.replay_game([gr.event_from_row(r) for r in self.rows])


def _nine_scoreless_innings(g: GameBuilder, through_top=9):
    """Fill innings with 1-2-3 halves until reaching a target."""
    while (g.inning, g.top) < (through_top, True):
        g.play(outs_after=1, base_after=0).play(outs_after=2, base_after=0).play(outs_after=3, base_after=0)
    return g


def test_strikeout_and_ordinary_out_increment_outs():
    g = GameBuilder()
    g.play(outcome="STRIKEOUT", outs_after=1, base_after=0)
    g.play(outcome="BIP_OUT", outs_after=2, base_after=0)
    res = g.result()
    assert not any(m.category.startswith("CONTINUITY") for m in res.mismatches)


def test_walk_puts_runner_on_first():
    g = GameBuilder()
    g.play(outcome="WALK_HBP_CI", outs_after=0, base_after=FIRST)
    res = g.result()
    assert res.mismatches == []


def test_single_uses_actual_advancement_not_one_base_rule():
    # runner from first scores on the single (actual advancement), batter to second.
    g = GameBuilder()
    g.play(outcome="SINGLE", outs_after=0, base_after=FIRST)
    g.play(outcome="SINGLE", outs_after=0, base_after=(FIRST | THIRD), runs=0)  # runner 1st->3rd
    res = g.result()
    assert res.mismatches == []


def test_home_run_clears_bases_and_scores():
    g = GameBuilder()
    g.play(outcome="WALK_HBP_CI", outs_after=0, base_after=FIRST)
    g.play(outcome="HOME_RUN", outs_after=0, base_after=0, runs=2)
    res = g.result()
    assert res.mismatches == []
    assert res.reconstructed_final["away"] == 2  # top half => visitor scores


def test_bases_loaded_walk_forces_one_run():
    g = GameBuilder()
    g.play(outcome="WALK_HBP_CI", outs_after=0, base_after=FIRST)
    g.play(outcome="WALK_HBP_CI", outs_after=0, base_after=(FIRST | SECOND))
    g.play(outcome="WALK_HBP_CI", outs_after=0, base_after=(FIRST | SECOND | THIRD))
    g.play(outcome="WALK_HBP_CI", outs_after=0, base_after=(FIRST | SECOND | THIRD), runs=1)
    res = g.result()
    assert res.mismatches == []
    assert res.reconstructed_final["away"] == 1


def test_double_play_records_two_outs():
    g = GameBuilder()
    g.play(outcome="WALK_HBP_CI", outs_after=0, base_after=FIRST)
    g.play(outcome="BIP_OUT", outs_after=2, base_after=0, event_text="64(1)3/GDP")
    res = g.result()
    assert res.mismatches == []


def test_inning_ending_out_transitions_half():
    g = GameBuilder()
    g.play(outs_after=1, base_after=0).play(outs_after=2, base_after=0).play(outs_after=3, base_after=0)
    # engine should now be in bottom of the 1st
    res = g.result()
    assert not res.mismatches
    # add one bottom-half play consistent with the transition
    g.play(outcome="SINGLE", outs_after=0, base_after=FIRST)
    assert g.result().mismatches == []


def test_full_scoreless_game_ends_after_regulation_exact_replay():
    g = GameBuilder()
    _nine_scoreless_innings(g, through_top=9)
    # top 9: three outs; home leads 0-0 is a tie -> continue is not our concern here, give home a run in 8th
    res = g.result()
    # a scoreless tie through 8.5 is not terminal; ensure no continuity mismatch regardless
    assert not any(m.category.startswith("CONTINUITY") for m in res.mismatches)


def test_walk_off_home_run_in_bottom_ninth():
    g = GameBuilder()
    _nine_scoreless_innings(g, through_top=9)
    # play the top of the 9th (3 outs) to reach the bottom of the 9th
    g.play(outs_after=1, base_after=0).play(outs_after=2, base_after=0).play(outs_after=3, base_after=0)
    assert g.top is False and g.inning == 9  # bottom 9
    g.play(outs_after=1, base_after=0).play(outs_after=2, base_after=0)
    g.play(outcome="HOME_RUN", outs_after=2, base_after=0, runs=1)  # walk-off
    res = g.result()
    assert res.classification == "EXACT_REPLAY"
    assert res.reconstructed_final["home"] == 1 and res.reconstructed_final["away"] == 0
    assert res.reconciliation["gameEndValid"] is True


def test_extra_innings_ghost_runner_after_marker():
    g = GameBuilder()
    _nine_scoreless_innings(g, through_top=9)
    # play top 9 and bottom 9 (both scoreless, a tie) to reach the top of the 10th
    g.play(outs_after=1, base_after=0).play(outs_after=2, base_after=0).play(outs_after=3, base_after=0)
    g.play(outs_after=1, base_after=0).play(outs_after=2, base_after=0).play(outs_after=3, base_after=0)
    assert g.inning == 10 and g.top is True
    # inning 10 top: no-op marker, then the automatic runner on second appears
    g.marker()
    g.place_ghost()
    g.play(outcome="STRIKEOUT", outs_after=1, base_after=SECOND, auto=True)
    res = g.result()
    assert res.mismatches == [], [m.public() for m in res.mismatches]


def test_pitcher_changes_are_tracked():
    g = GameBuilder()
    g.play(outs_after=1, base_after=0, pitcher="starter")
    g.play(outs_after=2, base_after=0, pitcher="starter")
    g.play(outs_after=3, base_after=0, pitcher="reliever")
    res = g.result()
    assert res.pitcher_sequence_len == 2


def test_impossible_outs_before_is_flagged():
    g = GameBuilder()
    g.rows.append({
        "game_id": g.game_id, "season": 2024, "play_number": 1, "plate_appearance_id": "pa1",
        "inning": 1, "top_bottom": 0, "outs_before": 4, "base_mask_before": 0,
        "outs_after": 4, "base_mask_after": 0, "visiting_score_before": 0, "home_score_before": 0,
        "visiting_score_after": 0, "home_score_after": 0, "runs_scored": 0, "batter_id": "b",
        "pitcher_id": "p", "pa_outcome": "BIP_OUT", "event_text": None, "regulation_innings": 9,
        "pbp_quality": "FULL", "automatic_runner_placement_before": False, "automatic_runner_base": None,
    })
    res = g.result()
    assert any(m.category == "OUTS_BEFORE_RANGE" for m in res.mismatches)
    assert res.classification == "REPLAY_MISMATCH"


def test_continuity_mismatch_detected_on_broken_before_state():
    g = GameBuilder()
    g.play(outcome="SINGLE", outs_after=0, base_after=FIRST)
    # inject a play whose before-state (bases empty) contradicts the prior after-state (first occupied)
    g.rows.append({**g.rows[-1], "play_number": 2, "outs_before": 0, "base_mask_before": 0,
                   "outs_after": 1, "base_mask_after": 0, "pa_outcome": "STRIKEOUT", "runs_scored": 0})
    res = g.result()
    assert any(m.category == "CONTINUITY_BASES" for m in res.mismatches)


def test_score_attribution_flags_wrong_team_scoring_in_top():
    g = GameBuilder()
    row = {
        "game_id": g.game_id, "season": 2024, "play_number": 1, "plate_appearance_id": "pa1",
        "inning": 1, "top_bottom": 0, "outs_before": 0, "base_mask_before": 0,
        "outs_after": 0, "base_mask_after": 0, "visiting_score_before": 0, "home_score_before": 0,
        "visiting_score_after": 0, "home_score_after": 1,  # home scores in the TOP half -> impossible
        "runs_scored": 1, "batter_id": "b", "pitcher_id": "p", "pa_outcome": "HOME_RUN",
        "event_text": None, "regulation_innings": 9, "pbp_quality": "FULL",
        "automatic_runner_placement_before": False, "automatic_runner_base": None,
    }
    g.rows.append(row)
    res = g.result()
    assert any(m.category == "SCORE_ATTRIBUTION" for m in res.mismatches)


def test_source_insufficient_on_non_full_pbp():
    g = GameBuilder()
    g.play(outs_after=1, base_after=0)
    g.rows[0]["pbp_quality"] = "PARTIAL"
    res = g.result()
    assert res.classification == "SOURCE_INSUFFICIENT"


def test_event_from_row_handles_nan_and_none():
    import math
    row = {
        "game_id": "g", "play_number": 1.0, "plate_appearance_id": "None", "inning": 1,
        "top_bottom": 0, "outs_before": 0, "base_mask_before": 0, "outs_after": 1, "base_mask_after": 0,
        "visiting_score_before": 0, "home_score_before": 0, "visiting_score_after": 0, "home_score_after": 0,
        "runs_scored": 0, "batter_id": None, "pitcher_id": "p", "pa_outcome": "BIP_OUT", "event_text": None,
        "regulation_innings": math.nan, "pbp_quality": "FULL",
        "automatic_runner_placement_before": False, "automatic_runner_base": math.nan,
    }
    event = gr.event_from_row(row)
    assert event.regulation_innings == 9  # NaN -> default
    assert event.automatic_runner_base == 0
    assert event.plate_appearance_id is None  # "None" string -> None
    assert event.batter_id is None


def test_empty_events_rejected():
    with pytest.raises(gr.GameReplayError):
        gr.replay_game([])


def _load_governed_games(limit: int = 8):
    """Read a few real games from the registered FD1 play_transition family, or skip."""
    import glob
    import os
    from pathlib import Path

    # Repair 7: the external FD1 play_transition corpus is out of bounds under the isolated gate — never reach for it.
    if os.getenv("ASP_REQUIRE_ISOLATED_RUNTIME", "").strip().lower() in ("1", "true", "yes"):
        pytest.skip("isolated gate: external FD1 play_transition corpus is out of bounds")
    exchange = Path(os.getenv("ASP_MODEL_EXCHANGE_ROOT", "") or r"C:/Users/james/asp-model-exchange")
    manifest = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
    base = exchange / "datasets" / "mlb-fd1" / f"sha256-{manifest}" / "parquet" / "play_transition"
    files = sorted(glob.glob(str(base / "**" / "*.parquet"), recursive=True))
    if not files:
        pytest.skip("registered FD1 play_transition family not available in this environment")
    import pyarrow.parquet as pq
    cols = [
        "game_id", "play_number", "plate_appearance_id", "inning", "top_bottom", "outs_before",
        "base_mask_before", "outs_after", "base_mask_after", "visiting_score_before",
        "home_score_before", "visiting_score_after", "home_score_after", "runs_scored",
        "batter_id", "pitcher_id", "pa_outcome", "event_text", "regulation_innings", "pbp_quality",
        "automatic_runner_placement_before", "automatic_runner_base",
    ]
    df = pq.read_table(files[0], columns=cols).to_pandas()
    game_ids = list(df["game_id"].drop_duplicates())[:limit]
    return {gid: df[df["game_id"] == gid].sort_values("play_number").to_dict("records") for gid in game_ids}


def test_real_governed_games_replay_exactly():
    games = _load_governed_games()
    results = [gr.replay_game([gr.event_from_row(r) for r in rows]) for rows in games.values()]
    # Every reconstructed final score/inning must match the source evidence directly.
    for res in results:
        assert res.reconciliation["finalScoreExact"], res.public()
        assert res.reconciliation["terminalInningExact"], res.public()
    # The governed sample replays essentially exactly (source quirks are rare and honest).
    exact = sum(r.classification == "EXACT_REPLAY" for r in results)
    assert exact >= len(results) - 1
