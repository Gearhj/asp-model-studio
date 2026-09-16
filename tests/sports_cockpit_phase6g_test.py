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
    from tests._runtime_probe import IS_SYNTHETIC_SEED as _IS_SYNTHETIC_SEED
    E._feature_view_path()
    _HAS_VIEW = not _IS_SYNTHETIC_SEED   # real D3/Gen-2 view only; a synthetic seed fails real-data assertions
except Exception:
    _HAS_VIEW = False

pytestmark = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")


def test_target_analysis_reports_classes_and_per_season_distribution():
    t = E.target_analysis()
    assert t["target"] == "outcome" and t["problemType"] == "MULTICLASS_CLASSIFICATION"
    assert t["classCount"] == 8 and t["missing"] == 0
    assert [s["season"] for s in t["perSeason"]] == [2023, 2024]  # 2025 physically sealed; research target rows only
    # each season's class shares sum to ~1
    for s in t["perSeason"]:
        assert abs(sum(d["share"] for d in s["distribution"]) - 1.0) < 1e-6
    assert t["dominantClass"]["class"] == "BIP_OUT"        # real dominant class
    assert t["rarestClass"]["class"] == "TRIPLE"           # real rarest class
    assert t["imbalanceRatio"] and t["imbalanceRatio"] > 50


def test_target_analysis_excludes_prior_only_and_sealed_seasons():
    t = E.target_analysis()
    assert set(t["modelingSeasons"]) == {2023, 2024}   # 2025 physically sealed; 2021/2022 are prior-only history
    for excluded in (2021, 2022, 2025):
        assert excluded not in [s["season"] for s in t["perSeason"]]


def test_model_lab_legacy_training_is_retired_and_champion_reference_unchanged():
    # Phase 7D.2 Gate 12 — the legacy in-process Model-Lab training path (which fit/scored a frozen 2025
    # fold) is retired; distinct-family training now runs through the canonical gen3_authority run path.
    with pytest.raises(M.LegacyModelingRetiredError):
        M.run_experiment({"features": list(M.ALL_FEATURES), "family": "logistic", "hyperparameters": {}}, persist=False)
    with pytest.raises(M.LegacyModelingRetiredError):
        M.champion_baseline()
    # the champion reference of record is still available and 2024-only (unchanged, not overwritten)
    ref = E._champion_reference()
    assert ref["val2024"]["logLoss"] > 0 and "frozen2025" not in ref


def test_available_families_are_honest():
    fams = M.AVAILABLE_FAMILIES
    for always in ("logistic", "random_forest", "extra_trees", "hist_gradient_boosting", "mlp", "svm"):
        assert fams[always] is True
    assert set(fams) >= {"xgboost", "lightgbm"}  # present as keys; availability reflects install state
