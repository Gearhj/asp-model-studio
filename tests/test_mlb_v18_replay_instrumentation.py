"""Small synthetic software fixtures; no fitted model or outcome/source reads."""
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.mlb_v18_replay_instrumentation import ReplayDiagnostics, RNGStreamAudit, compact_draw_records
from server.sports_current_statcast import mlb_v18_whole_game_challenger as engine
from server.sports_modeling.metrics import PA_CLASS_ORDER


class SyntheticTransitions:
    def distribution(self, outcome, outs, base):
        if outcome == "HOME_RUN":
            added, after, runs = 0, 0, base.bit_count() + 1
        elif outcome in {"STRIKEOUT", "BIP_OUT"}:
            added, after, runs = 1, base if outs < 2 else 0, 0
        elif outcome == "DOUBLE":
            added, after, runs = 0, ((base << 2) & 7) | 2, (base & 6).bit_count()
        elif outcome == "TRIPLE":
            added, after, runs = 0, 4, base.bit_count()
        else:
            added, after, runs = 0, ((base << 1) & 7) | 1, int(bool(base & 4))
        return {"transitions": [{"outsAdded": added, "baseMaskAfter": after, "runs": runs, "probability": 1.0}]}


class SyntheticProvider:
    def __init__(self, script=None):
        self.script = script

    def probabilities(self, **state):
        if self.script is None:
            return np.tile([.56, .10, .10, .14, .05, .01, .04, 0.0], (len(state["top"]), 1))
        values = np.zeros((len(state["top"]), 8))
        for i in range(len(values)):
            name = self.script(bool(state["top"][i]), int(state["inning"][i]), int(state["batting_pa"][i]))
            values[i, PA_CLASS_ORDER.index(name)] = 1.0
        return values


def run_pair(*, n=32, regulation=9, script=None, transition_model=None):
    args = dict(game_id="SYNTHETIC_REPLAY_SOFTWARE_FIXTURE", transition_model=transition_model or SyntheticTransitions(),
                n_sims=n, master_seed=20260919, regulation=regulation, trace_count=1)
    original_np, original_rng = engine.np, np.random.default_rng
    with RNGStreamAudit(engine) as baseline_rng:
        baseline = engine.simulate_prospective_game(provider=SyntheticProvider(script), **args)
    collector = ReplayDiagnostics(n, regulation=regulation)
    with RNGStreamAudit(engine) as observed_rng:
        observed = engine.simulate_prospective_game(provider=collector.wrap_provider(SyntheticProvider(script)),
                                                   event_observer=collector, **args)
    audit = baseline_rng.assert_equivalent(observed_rng)
    assert engine.np is original_np and np.random.default_rng is original_rng
    for key, value in baseline.items():
        if isinstance(value, np.ndarray):
            assert np.array_equal(value, observed[key]), key
        else:
            assert value == observed[key], key
    for stream in audit["streams"]:
        assert stream["randomValues"] == n * stream["randomCalls"]
        assert stream["initialState"] != stream["finalState"]
    arrays, metadata = collector.finalize(observed)
    assert metadata["accounting"]["allPassed"]
    assert metadata["replayInstrumentation"]["allPassed"]
    return arrays, metadata, observed, collector


def test_original_scores_traces_summaries_and_three_rng_streams_unchanged():
    arrays, meta, population, _ = run_pair()
    assert population["nonterminationCount"] == 0
    assert np.array_equal(arrays["joint_final_scores"],
                          arrays["joint_regulation_scores"] + arrays["joint_extra_inning_runs"])
    assert np.array_equal(arrays["starter_final_bf"] + arrays["relief_bf_total"], arrays["team_completed_pa"][:, ::-1])
    assert np.array_equal(arrays["starter_runs_while_active_total"] + arrays["relief_runs_while_active_total"], arrays["joint_final_scores"][:, ::-1])
    assert (arrays["starter_removal_reason"] == 1).any()
    assert "NOT official" in meta["replayInstrumentation"]["definitions"]["runExposure"]
    rows = compact_draw_records(arrays)
    assert len(rows) == 32 and rows[0]["draw_index"] == 0
    assert rows[0]["home_joint_final_scores"] == population["homeRuns"][0]


@pytest.mark.parametrize("outcome,expected_final,expected_excess", [("DOUBLE", 2, 1), ("HOME_RUN", 4, 0)])
def test_nonhr_walkoff_credit_is_observed_without_changing_original_score(outcome, expected_final, expected_excess):
    def script(top, inning, pa):
        return "STRIKEOUT" if top else ("SINGLE" if pa < 3 else outcome)
    arrays, _, pop, _ = run_pair(n=2, regulation=1, script=script)
    assert pop["homeRuns"].tolist() == [expected_final] * 2
    assert arrays["walkoff_nonhr_excess_credit"].tolist() == [expected_excess] * 2
    assert arrays["walkoff_runs_needed_to_win"].tolist() == [1, 1]
    assert arrays["walkoff"].all() and not arrays["extras_entered"].any()


def test_skipped_bottom_regulation_is_not_an_observed_batting_opportunity():
    def script(top, inning, pa):
        return "HOME_RUN" if not top and pa == 0 else "STRIKEOUT"
    arrays, _, pop, _ = run_pair(n=2, regulation=2, script=script)
    assert pop["homeRuns"].tolist() == [1, 1]
    assert arrays["skipped_bottom_regulation"].all()
    assert not arrays["skipped_bottom_ninth"].any()  # This fixture uses two innings.
    assert arrays["team_batting_half_opportunities"].tolist() == [[2, 1], [2, 1]]


def test_extras_keep_regulation_scores_and_automatic_runner_separate():
    def script(top, inning, pa):
        return "SINGLE" if not top and inning == 2 else "STRIKEOUT"
    arrays, _, pop, _ = run_pair(n=2, regulation=1, script=script)
    assert arrays["joint_regulation_scores"].tolist() == [[0, 0], [0, 0]]
    assert arrays["joint_final_scores"].tolist() == [[0, 1], [0, 1]]
    assert arrays["extras_entered"].all() and arrays["extras_observed"].all()
    assert arrays["automatic_runner_placements"].sum() == 4
    assert pop["innings"].tolist() == [2, 2]


def test_censored_early_inning_projection_does_not_claim_completed_regulation():
    arrays, _, pop, _ = run_pair(n=1, regulation=9, script=lambda *_: "HOME_RUN")
    assert pop["nonterminationCount"] == 1
    assert not arrays["regulation_complete"].any()
    assert not arrays["skipped_bottom_regulation"].any()
    assert arrays["starter_removal_reason"][0, 0] == 3  # Away starter never pitched.


def test_third_out_scoring_is_counted_without_asserting_force_or_runner_identity():
    class TimingUnspecifiedTransitions(SyntheticTransitions):
        def distribution(self, outcome, outs, base):
            if outcome == "BIP_OUT" and outs == 2 and base == 7:
                return {"transitions": [{"outsAdded": 1, "baseMaskAfter": 0, "runs": 1, "probability": 1.0}]}
            return super().distribution(outcome, outs, base)

    def script(top, inning, pa):
        if not top:
            return "HOME_RUN"
        return "SINGLE" if pa < 3 else "STRIKEOUT" if pa < 5 else "BIP_OUT"

    arrays, metadata, _, _ = run_pair(n=1, regulation=1, script=script, transition_model=TimingUnspecifiedTransitions())
    assert arrays["third_out_runs_by_batting_team"].tolist() == [[1, 0]]
    assert arrays["third_out_scoring_events_by_batting_team"].tolist() == [[1, 0]]
    assert "NOT a count of illegal runs" in metadata["replayInstrumentation"]["definitions"]["third_out_runs"]


def test_rng_namespace_restores_after_exception_and_rejects_nested_audit():
    original = engine.np
    with pytest.raises(RuntimeError, match="fixture failure"):
        with RNGStreamAudit(engine):
            with pytest.raises(RuntimeError, match="nested"):
                with RNGStreamAudit(engine):
                    pass
            raise RuntimeError("fixture failure")
    assert engine.np is original


def test_rng_different_consumption_is_detected():
    fake = SimpleNamespace(np=np)
    def consume(extra):
        with RNGStreamAudit(fake) as audit:
            seeds = np.random.SeedSequence(1).spawn(3)
            for seed in seeds:
                generator = fake.np.random.default_rng(seed)
                generator.random(2 + extra)
        return audit
    with pytest.raises(AssertionError, match="states differ"):
        consume(0).assert_equivalent(consume(1))
