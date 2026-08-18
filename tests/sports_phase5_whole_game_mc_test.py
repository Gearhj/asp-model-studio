"""Focused tests for the Phase 5D whole-game Monte Carlo engine and evaluation.

Hermetic where possible (termination, legality, reproducibility, extra innings, no ties,
baseline fixed-probability mode, and the CRPS / interval / Brier / calibration helpers).
Runtime-dependent checks (FastD3Fold reproduction, persisted record, registry projection)
skip cleanly when governed artifacts are absent. No D3 retraining, no whole-game forecasts
beyond the diagnostic study, no betting metrics.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5 import whole_game_monte_carlo as mc
from server.sports_phase5.game_initialization import RngLineage
from server.sports_phase5.pa_provider import D3_STATE_TABLE_SHA

REPO = Path(__file__).resolve().parents[1]
DYNAMIC_NS = REPO / ".runtime/asp-model-studio/sports-modeling/mlb-dynamic-player-state-v1"
PA_NS = REPO / ".runtime/asp-model-studio/sports-modeling/mlb-pa-v1"
MC_RECORD = REPO / ".runtime/asp-model-studio/sports-phase5/whole-game-monte-carlo/latest.montecarlo.json"

# Import CLI helpers by path (scripts/ is not a package).
_spec = importlib.util.spec_from_file_location("wg_mc_cli", REPO / "scripts" / "run_mlb_whole_game_monte_carlo.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def _tiny_model() -> bt.TransitionModel:
    recs = [{"pa_outcome": o, "outs_before": 0, "base_mask_before": 0, "outs_after": 1,
             "base_mask_after": 0, "runs_scored": 0, "season": 2021} for o in bt.PA_CLASSES]
    return bt.fit(recs, alpha=0.5, min_cell=1, seasons=(2021,))


def _zero_contribs(reg: int = 9) -> mc.GameContribs:
    z = np.zeros((mc.MAX_TEAM_PA, 8), dtype=np.float64)
    return mc.GameContribs(away_batter=z.copy(), away_pitcher=z.copy(),
                           home_batter=z.copy(), home_pitcher=z.copy(), regulation=reg)


# realistic league-average 8-class PA vector (order: SO, BB/HBP, HR, 1B, 2B, 3B, BIP_OUT, OTHER)
FIXED = np.array([0.225, 0.085, 0.033, 0.140, 0.045, 0.005, 0.440, 0.027])
FIXED = FIXED / FIXED.sum()


# --------------------------------------------------------------------------------------
# Engine (hermetic via fixed_probs; no D3 fold needed)
# --------------------------------------------------------------------------------------
def test_simulate_game_terminates_and_is_legal():
    sampler = mc.FastTransitionSampler(_tiny_model())
    r = mc.simulate_game(game_id="g", contribs=_zero_contribs(), fold=None, transition_sampler=sampler,
                         rng_lineage=RngLineage(1, "g"), n_sims=500, check_legality=True, fixed_probs=FIXED)
    assert r.nonterminated == 0
    assert r.illegal_states == 0
    assert np.all(r.away_runs >= 0) and np.all(r.home_runs >= 0)
    assert np.all(r.innings >= 9)
    # MLB games cannot end tied.
    assert np.all(r.away_runs != r.home_runs)


def test_same_seed_reproducible():
    sampler = mc.FastTransitionSampler(_tiny_model())
    kw = dict(game_id="g", contribs=_zero_contribs(), fold=None, transition_sampler=sampler,
              n_sims=300, fixed_probs=FIXED)
    a = mc.simulate_game(rng_lineage=RngLineage(7, "g"), **kw)
    b = mc.simulate_game(rng_lineage=RngLineage(7, "g"), **kw)
    assert np.array_equal(a.away_runs, b.away_runs)
    assert np.array_equal(a.home_runs, b.home_runs)
    assert np.array_equal(a.innings, b.innings)


def test_different_seed_diverges():
    sampler = mc.FastTransitionSampler(_tiny_model())
    kw = dict(game_id="g", contribs=_zero_contribs(), fold=None, transition_sampler=sampler,
              n_sims=300, fixed_probs=FIXED)
    a = mc.simulate_game(rng_lineage=RngLineage(7, "g"), **kw)
    c = mc.simulate_game(rng_lineage=RngLineage(8, "g"), **kw)
    assert not np.array_equal(a.away_runs, c.away_runs)


def test_extra_innings_occur_and_terminate():
    sampler = mc.FastTransitionSampler(_tiny_model())
    r = mc.simulate_game(game_id="g", contribs=_zero_contribs(), fold=None, transition_sampler=sampler,
                         rng_lineage=RngLineage(3, "g"), n_sims=2000, fixed_probs=FIXED)
    assert r.nonterminated == 0
    assert int(r.innings.max()) > 9  # some sampled games reach extra innings


def test_summary_shape():
    sampler = mc.FastTransitionSampler(_tiny_model())
    r = mc.simulate_game(game_id="g", contribs=_zero_contribs(), fold=None, transition_sampler=sampler,
                         rng_lineage=RngLineage(1, "g"), n_sims=200, fixed_probs=FIXED)
    s = r.summary()
    for key in ("meanAwayRuns", "meanHomeRuns", "meanTotalRuns", "homeWinProb", "totalQuantiles"):
        assert key in s
    assert 0.0 <= s["homeWinProb"] <= 1.0


def test_requires_fold_or_fixed_probs():
    sampler = mc.FastTransitionSampler(_tiny_model())
    with pytest.raises(mc.MonteCarloError):
        mc.simulate_game(game_id="g", contribs=_zero_contribs(), fold=None, transition_sampler=sampler,
                         rng_lineage=RngLineage(1, "g"), n_sims=10, fixed_probs=None)


# --------------------------------------------------------------------------------------
# Evaluation helpers
# --------------------------------------------------------------------------------------
def test_crps_matches_reference():
    def ref(x, y):
        x = np.asarray(x, float)
        return float(np.mean(np.abs(x - y)) - 0.5 * np.mean(np.abs(x[:, None] - x[None, :])))
    for x, y in ([0.0, 2.0], 1.0), ([2, 2, 2, 2], 5.0), ([1, 3, 5, 7, 9], 4.0):
        assert abs(cli._crps(np.array(x, float), y) - ref(x, y)) < 1e-9
    # point-mass CRPS equals |c - y|
    assert abs(cli._crps(np.full(50, 4.0), 7.0) - 3.0) < 1e-9


def test_interval_hits():
    s = np.arange(0, 100, dtype=float)  # 0..99
    hits = cli._interval_hits(s, 50.0)
    assert hits["90"] == 1 and hits["50"] == 1
    hits_out = cli._interval_hits(s, 99.0)
    assert hits_out["50"] == 0  # 99 outside the central 50% interval


def test_brier_logloss():
    recs = [{"pHome": 1.0, "homeWon": 1}, {"pHome": 0.0, "homeWon": 0}]
    m = cli._brier_logloss(recs)
    assert m["brier"] < 1e-6
    recs2 = [{"pHome": 0.5, "homeWon": 1}, {"pHome": 0.5, "homeWon": 0}]
    assert abs(cli._brier_logloss(recs2)["brier"] - 0.25) < 1e-9


def test_calibration_bins():
    recs = [{"pHome": p, "homeWon": int(p > 0.5)} for p in np.linspace(0.01, 0.99, 50)]
    cal = cli._calibration_bins(recs, n_bins=5)
    assert len(cal["bins"]) == 5
    assert cal["ece"] >= 0.0


def test_score_metrics_bias_sign():
    recs = [{"meanAway": 5, "meanHome": 5, "meanTotal": 10, "meanDiff": 0,
             "actualAway": 4, "actualHome": 4, "actualTotal": 8, "actualDiff": 0,
             "crpsAway": 0, "crpsHome": 0, "crpsTotal": 0} for _ in range(10)]
    sm = cli._score_metrics(recs)
    assert abs(sm["total"]["bias"] - 2.0) < 1e-9  # simulated 10 vs actual 8


# --------------------------------------------------------------------------------------
# Fast D3 fold reproduction (runtime-dependent)
# --------------------------------------------------------------------------------------
def _runtime_present() -> bool:
    return (DYNAMIC_NS / "objects/sha256" / D3_STATE_TABLE_SHA[:2] / D3_STATE_TABLE_SHA / "mlb-dynamic-player-state-v1.parquet").is_file()


@pytest.mark.skipif(not _runtime_present(), reason="governed D3 runtime artifacts not present")
def test_fastd3fold_reproduces_provider():
    import glob
    import pyarrow.parquet as pq
    from server.sports_phase5.pa_provider import D3ProbabilisticPAProvider, PAInvocationContext, PlayerStateResolver

    state = pq.read_table(str(DYNAMIC_NS / "objects/sha256" / D3_STATE_TABLE_SHA[:2] / D3_STATE_TABLE_SHA / "mlb-dynamic-player-state-v1.parquet")).to_pandas()
    resolver = PlayerStateResolver.from_records(state.to_dict("records"), state_table_sha=D3_STATE_TABLE_SHA)
    provider = D3ProbabilisticPAProvider.from_runtime(dynamic_namespace_root=DYNAMIC_NS, resolver=resolver)
    fold = mc.FastD3Fold.from_model(provider._models[2024])
    fv = pq.read_table(glob.glob(str(PA_NS / "objects/sha256/**/mlb-pa-feature-view-v1.parquet"), recursive=True)[0]).to_pandas()
    sub = fv[fv["season"] == 2024].head(500).reset_index(drop=True)
    contexts = [PAInvocationContext(game_id=str(r.game_id), game_date=str(r.game_date), season=2024,
        inning=int(r.context_inning), top=(int(r.context_top_bottom) == 0), outs_before=int(r.context_outs_before),
        base_mask_before=int(r.context_base_mask_before), batting_score_diff_before=int(r.context_batting_score_diff_before),
        batter_uuid=str(r.batter_canonical_player_uuid), pitcher_uuid=str(r.pitcher_canonical_player_uuid))
        for r in sub.itertuples(index=False)]
    ref = np.array([resp.probabilities for resp in provider.score_batch(contexts)])
    inning = sub["context_inning"].to_numpy()
    tb = np.where(sub["context_top_bottom"].to_numpy() == 0, 0, 1)
    outs = sub["context_outs_before"].to_numpy()
    base = sub["context_base_mask_before"].to_numpy()
    sd = sub["context_batting_score_diff_before"].to_numpy()
    zc = fold.context_base_logits(inning, tb, outs, base, sd)
    bc = np.array([fold.batter_contrib(np.asarray(resolver.resolve(str(r.batter_canonical_player_uuid), "BATTER", str(r.game_date)), float)) for r in sub.itertuples(index=False)])
    pc = np.array([fold.pitcher_contrib(np.asarray(resolver.resolve(str(r.pitcher_canonical_player_uuid), "PITCHER", str(r.game_date)), float)) for r in sub.itertuples(index=False)])
    fast = mc._softmax_rows(zc + bc + pc)
    assert np.abs(fast - ref).max() < 1e-12


# --------------------------------------------------------------------------------------
# Persisted record / registry (runtime-dependent)
# --------------------------------------------------------------------------------------
def _strip_disclaimers(value):
    """Remove free-text disclaimer fields so we scan metrics, not 'no betting' negations."""
    if isinstance(value, dict):
        return {k: _strip_disclaimers(v) for k, v in value.items()
                if k not in ("limitations", "note", "notes", "label")}
    if isinstance(value, list):
        return [_strip_disclaimers(v) for v in value]
    return value


@pytest.mark.skipif(not MC_RECORD.is_file(), reason="monte-carlo record not present")
def test_no_sportsbook_or_betting_metrics():
    payload = json.loads(MC_RECORD.read_text(encoding="utf-8"))["monteCarlo"]
    text = json.dumps(_strip_disclaimers(payload)).lower()
    # Disclaimer/limitation text is excluded; the metric payload must carry no betting metrics.
    for banned in ("moneyline", "run_line", "runline", "closing odds", "clv", "sportsbook",
                   "market edge", "roi", "parlay", "wager", "vigorish"):
        assert banned not in text, f"forbidden betting token present: {banned}"


@pytest.mark.skipif(not MC_RECORD.is_file(), reason="monte-carlo record not present")
def test_record_is_oracle_and_legal():
    payload = json.loads(MC_RECORD.read_text(encoding="utf-8"))["monteCarlo"]
    assert payload["participantMode"] == "HISTORICAL_PARTICIPANTS_ORACLE_MODE"
    assert payload["legality"]["totalIllegalStates"] == 0
    assert payload["simulatorReadiness"] in (
        "WHOLE_GAME_SIMULATOR_RESEARCH_BASELINE_READY", "WHOLE_GAME_SIMULATOR_PARTIALLY_READY")


@pytest.mark.skipif(not MC_RECORD.is_file(), reason="monte-carlo record not present")
def test_registry_projection_authority_gated():
    from server.sports_datasets.registry import _load_active_whole_game_monte_carlo
    payload = json.loads(MC_RECORD.read_text(encoding="utf-8"))["monteCarlo"]
    auth = payload["datasetAuthority"]
    good = _load_active_whole_game_monte_carlo({"registration_id": auth["registrationId"], "manifest_sha": auth["manifestSha"]})
    assert good is not None
    assert good["participantMode"] == "HISTORICAL_PARTICIPANTS_ORACLE_MODE"
    assert _load_active_whole_game_monte_carlo({"registration_id": "x", "manifest_sha": "y"}) is None
