"""Phase 6B tests: generic PA provider + full simulator decoupling, custom feature engineering,
ablation, and the exploratory segmentation workbench.

Runtime-dependent checks skip when the D3 feature view / governed play_transition are absent.
No D3 retraining that mutates registered artifacts; no betting logic.
"""

from __future__ import annotations

import numpy as np
import pytest

from server.sports_cockpit import engine as E
from server.sports_cockpit import features_builder as FB
from server.sports_cockpit import modeling as M
from server.sports_cockpit import provider as PROV
from server.sports_modeling.metrics import PA_CLASS_ORDER

_HAS_VIEW = True
try:
    E._feature_view_path()
except Exception:
    _HAS_VIEW = False

_HAS_PT = True
try:
    import glob
    from server.sports_cockpit import game_preps as GP
    _HAS_PT = bool(glob.glob(GP.PLAY_TRANSITION_GLOB, recursive=True))
except Exception:
    _HAS_PT = False

view = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")
sim = pytest.mark.skipif(not (_HAS_VIEW and _HAS_PT), reason="feature view / play_transition unavailable")


# ----------------------------------------------------------------- generic provider
@view
def test_fold_reproduces_model_bitforbit():
    r = PROV.verify_fold_reproduces_model(
        {"features": list(E.ALL_FEATURES), "family": "logistic", "hyperparameters": {"C": 0.05}, "missingPolicy": {"globalMethod": "mean"}},
        n=1500,
    )
    assert r["equivalent"] is True
    assert r["maxAbsProbDiff"] < 1e-6
    assert r["classMismatch"] == 0


@view
def test_fold_reproduces_subset_with_policies():
    r = PROV.verify_fold_reproduces_model(
        {"features": list(E.BATTER_FEATURES) + list(E.PITCHER_FEATURES) + ["context_outs_before", "context_base_mask_before"],
         "family": "logistic", "hyperparameters": {"C": 1.0}, "outlierPolicy": {"globalMethod": "iqr", "params": {"k": 3.0}}},
        n=1500,
    )
    assert r["equivalent"] is True


def test_feature_availability_classification():
    assert PROV.classify_feature("context_outs_before") == PROV.SIMULATION_DYNAMIC_STATE
    assert PROV.classify_feature("batter_obp") == PROV.PRIOR_PLAYER_STATE
    assert PROV.classify_feature("pitcher_era9") == PROV.PRIOR_PLAYER_STATE
    assert PROV.classify_feature("some_engineered_feature") == PROV.NOT_SIMULATOR_AVAILABLE


def test_eligibility_gate():
    assert PROV.simulator_eligibility({"features": list(E.ALL_FEATURES), "family": "logistic"})["eligible"] is True
    assert PROV.simulator_eligibility({"features": list(E.ALL_FEATURES), "family": "random_forest"})["eligible"] is False
    # a model using an engineered (non-reconstructable) feature is not full-eligible
    e = PROV.simulator_eligibility({"features": list(E.ALL_FEATURES) + ["cal_month"], "family": "logistic"})
    assert e["eligible"] is False and "cal_month" in e["blockedFeatures"]


# ----------------------------------------------------------------- full simulator
@sim
def test_full_lineup_rotation_simulation_runs():
    from server.sports_cockpit import simulation as S

    cfg = {"features": list(E.ALL_FEATURES), "family": "logistic", "hyperparameters": {"C": 1.0}}
    out = S.simulate_full_impact(cfg, season=E.VAL_SEASON, n_games=6, n_sims=60)
    assert out["mode"] == "FULL_LINEUP_ROTATION"
    assert out["provider"] == PROV.PROBABILISTIC_PA_PROVIDER_V1
    assert out["games"] >= 1
    assert out["verdict"] in {"GAME_LEVEL_IMPROVEMENT", "PA_ONLY_IMPROVEMENT", "NO_MATERIAL_CHANGE", "GAME_LEVEL_DEGRADATION"}
    for who in ("champion", "challenger"):
        assert 0.0 <= out[who]["coverage90"] <= 1.0
        assert out[who]["paLogLoss"] > 0
        assert out[who]["homeWinBrier"] >= 0


@sim
def test_full_simulation_rejects_ineligible_model():
    from server.sports_cockpit import simulation as S

    with pytest.raises(E.CockpitError):
        S.simulate_full_impact({"features": list(E.ALL_FEATURES), "family": "random_forest"}, season=E.VAL_SEASON, n_games=4, n_sims=30)


@sim
def test_game_preps_resolve_participants():
    from server.sports_cockpit import game_preps as GP

    frame = E.load_frame()
    games = sorted(frame.loc[frame["season"].to_numpy() == E.VAL_SEASON, "game_id"].unique())[:20]
    preps = GP.build_preps(E.VAL_SEASON, games)
    assert len(preps) >= 1
    p = preps[0]
    assert len(p.away_start) == 9 and len(p.home_start) == 9
    assert len(p.away_pa) >= 9 and len(p.home_pa) >= 9
    assert all(isinstance(x, tuple) and len(x) == 2 for x in p.away_pa)


# ----------------------------------------------------------------- feature engineering
@view
def test_materialize_all_kinds():
    frame = E.load_frame()
    dev = frame["season"].to_numpy() == E.DEV_SEASON
    specs = [
        {"name": "f1", "kind": "arithmetic", "inputs": ["batter_obp", "pitcher_whip"], "params": {"op": "sub"}},
        {"name": "f2", "kind": "ratio", "inputs": ["batter_hr_per_pa", "batter_so_per_pa"]},
        {"name": "f3", "kind": "interaction", "inputs": ["batter_obp", "pitcher_era9"]},
        {"name": "f4", "kind": "log", "inputs": ["pitcher_era9"]},
        {"name": "f5", "kind": "power", "inputs": ["batter_slg"], "params": {"exponent": 2}},
        {"name": "f6", "kind": "bin", "inputs": ["batter_avg"], "params": {"bins": 5}},
        {"name": "f7", "kind": "indicator", "inputs": ["batter_hr_per_pa"], "params": {"threshold": 0.04}},
        {"name": "f8", "kind": "calendar", "params": {"subkind": "month"}},
    ]
    for spec in specs:
        col = FB.materialize(frame, spec, dev)
        assert col.shape[0] == len(frame)
    # bins produce a bounded set of integers
    b = FB.materialize(frame, specs[5], dev)
    assert set(np.unique(b[np.isfinite(b)]).astype(int)).issubset(set(range(6)))
    # indicator is 0/1
    ind = FB.materialize(frame, specs[6], dev)
    assert set(np.unique(ind)).issubset({0.0, 1.0})


@view
def test_calendar_is_temporally_safe_month_range():
    frame = E.load_frame()
    month = FB._calendar_column(frame, "month")
    assert np.nanmin(month) >= 1 and np.nanmax(month) <= 12
    dss = FB._calendar_column(frame, "days_since_season_start")
    assert np.nanmin(dss) >= 0  # never negative → derived from prior season start, not the future


@view
def test_engineered_feature_flows_through_experiment():
    spec = {"name": "obp_minus_whip", "kind": "arithmetic", "inputs": ["batter_obp", "pitcher_whip"], "params": {"op": "sub"}}
    res = M.run_experiment(
        {"features": list(E.ALL_FEATURES) + ["obp_minus_whip"], "family": "logistic", "hyperparameters": {"C": 1.0}, "engineeredFeatures": [spec]},
        persist=False,
    )
    assert res["featureCount"] == len(E.ALL_FEATURES) + 1
    assert res["metrics"]["val2024"]["logLoss"] > 0


@view
def test_ablation_produces_verdict():
    spec = {"name": "cal_month", "kind": "calendar", "params": {"subkind": "month"}}
    out = M.run_ablation({"baseConfig": {"features": list(E.ALL_FEATURES), "family": "logistic", "hyperparameters": {"C": 1.0}},
                          "addFeatures": ["cal_month"], "addEngineered": [spec]})
    assert out["verdict"] in {"VALUE_CONFIRMED", "VALUE_MARGINAL", "NO_MATERIAL_VALUE", "NEGATIVE_VALUE"}
    assert out["control"]["features"] == 22 and out["challenger"]["features"] == 23


@view
def test_profile_engineered_returns_iv_mi_and_sim_availability():
    p = FB.profile_engineered({"name": "obp_x_whip", "kind": "interaction", "inputs": ["batter_obp", "pitcher_whip"]})
    assert set(p["iv"]["perClass"].keys()) == set(PA_CLASS_ORDER)
    assert "quick-sim only" in p["simulatorAvailability"]
    assert p["mi"] >= -1e-9


# ----------------------------------------------------------------- segmentation
@view
def test_segmentation_kmeans_diagnostics():
    from server.sports_cockpit import segmentation as SEG

    out = SEG.run_kmeans("BATTERS", [], 2, 6)
    assert out["players"] > 50
    ks = [r["k"] for r in out["results"]]
    assert ks == list(range(2, 7))
    for r in out["results"]:
        assert -1.0 <= r["silhouette"] <= 1.0
        assert r["daviesBouldin"] >= 0
        assert len(r["clusterSizes"]) == r["k"]
    assert 2 <= out["recommendedK"] <= 6


@view
def test_segmentation_grid_dev_boundaries_and_pca():
    from server.sports_cockpit import segmentation as SEG

    g = SEG.grid_3x3("BATTERS", "batter_hr_per_pa", "batter_so_per_pa")
    assert len(g["cells"]) == 9
    assert g["boundaryScope"] == "DEVELOPMENT_ONLY"
    assert abs(sum(c["paShare"] for c in g["cells"]) - 1.0) < 1e-6
    p = SEG.pca_scatter("BATTERS", [], 3)
    assert len(p["explainedVariance"]) == 2 and 0 < sum(p["explainedVariance"]) <= 1.0
    assert len(p["profiles"]) == 3


@view
def test_segmentation_never_touches_pa_model():
    # segmentation module exposes no training/mutation of the PA model
    from server.sports_cockpit import segmentation as SEG

    assert not hasattr(SEG, "run_experiment")
    assert not hasattr(SEG, "promote")
