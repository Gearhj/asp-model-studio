"""Synthetic terminal-credit accounting checks; no model/simulator execution."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from mlb_v18_walkoff_experiment import (
    BASELINE_SOURCE_SHA256, TerminalCreditContext, TerminalCreditError,
    build_terminal_credit_simulator,
)


def event(*, outcome="DOUBLE", runs=3, away=4, home_after=6, inning=9, half="BOTTOM"):
    return {
        "pa": 76, "inning": inning, "half": half, "battingOrderPosition": 3,
        "pitcherState": "TEAM_BULLPEN", "pitchingChange": False,
        "outcome": outcome, "outsBefore": 1, "outsAfter": 1,
        "baseMaskBefore": 7, "baseMaskAfter": 2, "runsScored": runs,
        "awayScoreAfter": away, "homeScoreAfter": home_after,
    }


def test_non_hr_credit_uses_terminal_event_and_preserves_raw_evidence():
    raw = event()
    original = copy.deepcopy(raw)
    forwarded = []
    context = TerminalCreditContext(2, observer=lambda i, e: forwarded.append((i, copy.deepcopy(e))))
    context.observe(0, raw)
    away = np.array([4, 2])
    home = np.array([6, 1])
    credited = context.apply(away, home, np.array([True, True]))
    assert credited.tolist() == [5, 1]
    assert home.tolist() == [6, 1] and away.tolist() == [4, 2]
    assert raw == original and forwarded == [(0, original)]
    assert context.summary["rawTerminalEvents"][0]["rawTransition"] == [0, 2, 3]
    assert context.summary["rawTerminalEvents"][0]["runsNeededForLead"] == 2
    assert context.summary["terminalCreditReduction"].tolist() == [1, 0]
    assert np.array_equal(home > away, credited > away)


@pytest.mark.parametrize("outcome", ["HOME_RUN"])
def test_full_home_run_credit_preserved(outcome):
    context = TerminalCreditContext(1)
    context.observe(0, event(outcome=outcome))
    assert context.apply(np.array([4]), np.array([6]), np.array([True])).tolist() == [6]
    assert context.summary["changedSimulationCount"] == 0


@pytest.mark.parametrize("inning,half,home,away", [(8, "BOTTOM", 6, 4), (9, "TOP", 6, 4), (9, "BOTTOM", 4, 4)])
def test_nonterminal_or_pre_regulation_events_are_not_credited(inning, half, home, away):
    context = TerminalCreditContext(1)
    context.observe(0, event(inning=inning, half=half, home_after=home, away=away))
    assert context.apply(np.array([away]), np.array([home]), np.array([True])).tolist() == [home]
    assert context.summary["walkoffCount"] == 0


def test_extra_inning_non_hr_credit_and_single_run_no_change():
    context = TerminalCreditContext(2)
    context.observe(0, event(inning=12))
    context.observe(1, event(outcome="WALK", runs=1, away=4, home_after=5))
    assert context.apply(np.array([4, 4]), np.array([6, 5]), np.array([True, True])).tolist() == [5, 5]
    assert context.summary["changedSimulationCount"] == 1


def test_event_after_walkoff_fails_closed():
    context = TerminalCreditContext(1)
    context.observe(0, event())
    with pytest.raises(TerminalCreditError, match="event after"):
        context.observe(0, event())


@pytest.mark.parametrize("home,terminal", [(7, True), (6, False)])
def test_final_event_mismatch_fails_closed(home, terminal):
    context = TerminalCreditContext(1)
    context.observe(0, event())
    with pytest.raises(TerminalCreditError, match="raw final scores"):
        context.apply(np.array([4]), np.array([home]), np.array([terminal]))


def test_already_leading_before_event_fails_closed():
    context = TerminalCreditContext(1)
    with pytest.raises(TerminalCreditError, match="first lead-taking"):
        context.observe(0, event(runs=1, away=4, home_after=6))


def test_one_source_insertion_builds_without_running_and_leaves_core_untouched():
    from server.sports_current_statcast import mlb_v18_whole_game_challenger as core
    original = core.simulate_prospective_game
    original_numpy = core.np
    function, binding = build_terminal_credit_simulator(core)
    assert callable(function)
    assert binding["baselineSourceSha256"] == BASELINE_SOURCE_SHA256
    assert binding["insertionCount"] == 1
    assert binding["annotatedDiff"].count("+    home_score = _terminal_credit_context.apply") == 1
    assert core.simulate_prospective_game is original and core.np is original_numpy
    json.dumps(binding)


def test_source_mismatch_fails_before_build(tmp_path):
    class FakeCore:
        __file__ = str(tmp_path / "bad.py")
    Path(FakeCore.__file__).write_text("# deliberately unbound synthetic source\n")
    assert hashlib.sha256(Path(FakeCore.__file__).read_bytes()).hexdigest() != BASELINE_SOURCE_SHA256
    with pytest.raises(TerminalCreditError, match="source binding mismatch"):
        build_terminal_credit_simulator(FakeCore)
