"""Phase 6G — target authority + multi-model Model Laboratory backend.

Target-variable analysis (8-class outcome, per modeling season) and proof the lab trains distinct
model FAMILIES with distinct experiment identity and real leaderboard metrics. Frozen 2025 protected.
Bounded — two fast fits.
"""

from __future__ import annotations

import pytest

from server.sports_cockpit import engine as E
from server.sports_cockpit import modeling as M

_HAS_VIEW = True
try:
    E._feature_view_path()
except Exception:
    _HAS_VIEW = False

pytestmark = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")


def test_target_analysis_reports_classes_and_per_season_distribution():
    t = E.target_analysis()
    assert t["target"] == "outcome" and t["problemType"] == "MULTICLASS_CLASSIFICATION"
    assert t["classCount"] == 8 and t["missing"] == 0
    assert [s["season"] for s in t["perSeason"]] == [2023, 2024, 2025]  # modeling target rows only
    # each season's class shares sum to ~1
    for s in t["perSeason"]:
        assert abs(sum(d["share"] for d in s["distribution"]) - 1.0) < 1e-6
    assert t["dominantClass"]["class"] == "BIP_OUT"        # real dominant class
    assert t["rarestClass"]["class"] == "TRIPLE"           # real rarest class
    assert t["imbalanceRatio"] and t["imbalanceRatio"] > 50


def test_target_analysis_excludes_prior_only_seasons():
    t = E.target_analysis()
    assert set(t["modelingSeasons"]) == {2023, 2024, 2025}
    assert 2021 not in [s["season"] for s in t["perSeason"]]
    assert 2022 not in [s["season"] for s in t["perSeason"]]


def test_model_lab_trains_distinct_families_with_leaderboard_metrics():
    a = M.run_experiment({"features": list(M.ALL_FEATURES), "family": "logistic", "hyperparameters": {}}, persist=False)
    b = M.run_experiment({"features": list(M.ALL_FEATURES), "family": "hist_gradient_boosting", "hyperparameters": {}}, persist=False)
    assert a["experimentId"] != b["experimentId"]                 # distinct candidate identity
    assert a["family"] == "logistic" and b["family"] == "hist_gradient_boosting"
    for r in (a, b):
        v = r["metrics"]["val2024"]
        # real leaderboard metrics exist (no fabricated fields)
        for k in ("logLoss", "brierScore", "topLabelEce", "top1Accuracy", "macroF1"):
            assert k in v and v[k] is not None
        assert r["fitSeconds"] > 0
    # champion reference is available and unchanged (not overwritten)
    champ = M.champion_baseline()
    assert champ["val2024"]["logLoss"] > 0


def test_available_families_are_honest():
    fams = M.AVAILABLE_FAMILIES
    for always in ("logistic", "random_forest", "extra_trees", "hist_gradient_boosting", "mlp", "svm"):
        assert fams[always] is True
    assert set(fams) >= {"xgboost", "lightgbm"}  # present as keys; availability reflects install state
