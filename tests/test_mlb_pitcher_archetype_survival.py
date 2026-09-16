"""Focused synthetic fixture fits only; no real source payloads or publication."""
from io import BytesIO
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

from server.sports_current_statcast import mlb_pitcher_archetype_survival as subject
from server.sports_current_statcast.mlb_starter_survival_models import (
    LearnedHazard, PREGAME_FIELDS, pregame_bf_distribution as frozen_bf_distribution,
)


@pytest.fixture(autouse=True)
def synthetic_style_registry(monkeypatch):
    # Registration rules are exercised without reading any source or fitted file.
    monkeypatch.setattr(subject, "_style_fields", lambda: ("style_throws_left", "style_speed_mph"))


def frame(count=18):
    rng = np.random.default_rng(1947)
    return pd.DataFrame({
        "homePitcher": np.arange(count) % 2, "calendarMonth": 3 + np.arange(count) % 7,
        "priorStartCount": np.arange(count) % 30,
        "priorStartBfMean": rng.normal(23, 3, count),
        "daysRest": 3 + np.arange(count) % 5,
        "historyMissing": np.zeros(count), "bf": 1 + np.arange(count) % 33,
    })


def constant_model(probabilities=(0.8, 0.15, 0.05), *, profile=False):
    order = PREGAME_FIELDS + (("style_throws_left",) if profile else ())
    return SimpleNamespace(
        model_id="TEST_RESEARCH_ONLY", feature_order=order,
        predict_proba=lambda rows, **kwargs: np.tile(probabilities, (len(rows), 1)),
    )


def test_matched_specification_exact_predictions_and_reload():
    x = frame(650)
    x.loc[x.index[::11], "priorStartBfMean"] = np.nan
    y = np.where(np.arange(len(x)) % 29 == 0, "GAME_END",
                 np.where(np.arange(len(x)) % 7 == 0, "REMOVAL", "CONTINUE"))
    with threadpool_limits(limits=1):
        original = LearnedHazard("HGB_PREGAME", PREGAME_FIELDS).fit(x, y)
        candidate = subject.ArchetypeHazard("A_MATCHED_REFIT", PREGAME_FIELDS).fit(x, y)
        assert np.array_equal(candidate.predict_proba(x), original.predict_proba(x))
        calibration = candidate.fit_temperature(x.iloc[:90], y[:90])
        assert 0.5 <= calibration["temperature"] <= 2.0
        buffer = BytesIO()
        joblib.dump(candidate, buffer)
        buffer.seek(0)
        loaded = joblib.load(buffer)
        assert np.array_equal(candidate.predict_proba(x), loaded.predict_proba(x))


@pytest.mark.parametrize("extra", ["runsAllowedSoFar", "observedPitches", "futureVelocity"])
def test_future_or_unregistered_features_rejected(extra):
    with pytest.raises(ValueError, match="REGISTERED_PREGAME"):
        subject.ArchetypeHazard("B_CONTINUOUS_PROFILE", PREGAME_FIELDS + (extra,))


def test_distinct_identity_and_membership_order_are_required():
    with pytest.raises(ValueError, match="DISTINCT_RESEARCH"):
        subject.ArchetypeHazard("HGB_PREGAME", PREGAME_FIELDS)
    with pytest.raises(ValueError, match="CONTIGUOUS"):
        subject.ArchetypeHazard("C_ARCHETYPE", PREGAME_FIELDS + ("archetype_p1",))


def test_missing_endpoint_not_fabricated():
    with pytest.raises(ValueError, match="THREE_REAL_ENDPOINTS"):
        subject.ArchetypeHazard("A_MATCHED_REFIT", PREGAME_FIELDS).fit(frame(), ["CONTINUE"] * 18)


def test_competing_bf_accounting_and_frozen_equivalence():
    starts, model = frame(2), constant_model()
    got = subject.pregame_bf_distribution(model, starts, maximum_bf=10)
    expected = frozen_bf_distribution(model, starts, maximum_bf=10)
    for key in got:
        assert np.array_equal(got[key], expected[key])
    assert np.allclose(got["causeMass"].sum(axis=(1, 2)) + got["tail"], 1)
    assert np.allclose(got["tail"], 0.8 ** 10)
    assert np.allclose(got["causeMass"][:, :, 1].sum(axis=1), 0.25 * (1 - 0.8 ** 10))


def test_profile_bf_law_and_duplicate_dataframe_index():
    starts = frame(2).assign(style_throws_left=[0, 1])
    starts.index = [7, 7]
    result = subject.pregame_bf_distribution(constant_model(profile=True), starts, maximum_bf=10)
    assert result["pmf"].shape == (2, 10)


def test_runtime_conditions_on_next_opportunity_and_never_hooks_bf_zero():
    x = frame(5)
    x["bf"] = [0, 1, 2, 3, 4]
    got = subject.conditional_removal_probability(
        constant_model(), x, game_active=[True, True, False, True, True],
        starter_active=[True, True, True, False, True],
    )
    assert np.allclose(got, [0, 0.15 / 0.95, 0, 0, 0.15 / 0.95])
    with pytest.raises(ValueError, match="NO_SUPPORTED_NEXT"):
        subject.conditional_removal_probability(
            constant_model((0, 0, 1)), frame(1), game_active=[True], starter_active=[True])


def test_profile_fallback_returns_identical_baseline_without_candidate_call():
    model = constant_model(profile=True)
    model.predict_proba = lambda *args, **kwargs: pytest.fail("Unsupported profile reached inference")
    baseline = {"homeRuns": [1, 5], "awayRuns": [2, 4], "baselineId": "immutable-example"}
    result = subject.research_duration_lookup(
        model, {"profileSupported": False}, {"profileSupported": True}, baseline_result=baseline)
    assert result["result"] is baseline
    assert result["fallback"] is True
    assert result["candidateExecuted"] is False
    assert result["lookup"] is None


def test_supported_lookup_is_inference_not_a_game_publication():
    inputs = frame(2).assign(style_throws_left=[0, 1], profileSupported=True)
    away, home = inputs.iloc[0].to_dict(), inputs.iloc[1].to_dict()
    result = subject.research_duration_lookup(
        constant_model(profile=True), home, away, baseline_result=object(), maximum_bf=12)
    assert result["lookup"].shape == (2, 13)
    assert np.array_equal(result["lookup"][:, 0], [0, 0])
    assert np.allclose(result["lookup"][:, 1:], 0.15 / 0.95)
    assert result["candidateHazardExecuted"] is True
    assert result["gameSimulationExecuted"] is False
    assert result["candidateExecuted"] is False


def cluster_frame():
    rng = np.random.default_rng(41)
    return pd.DataFrame({
        "startId": [f"synthetic-{i}" for i in range(300)],
        "pitcherId": [f"synthetic-pitcher-{i % 30}" for i in range(300)],
        "profileSupported": True,
        "style_throws_left": np.repeat([0.0, 1.0], 150),
        "style_speed_mph": np.concatenate([rng.normal(98, 0.2, 150), rng.normal(88, 0.2, 150)]),
        "bf": rng.integers(1, 40, 300), "daysRest": rng.integers(1, 10, 300),
    })


def test_clustering_training_only_support_soft_mass_and_no_future_transform_fit():
    train = cluster_frame()
    with threadpool_limits(limits=1):
        membership = subject.ArchetypeMembership(cluster_counts=(2,)).fit(train)
    assert membership.supported and membership.selected_k == 2
    assert membership.feature_order == ("style_throws_left", "style_speed_mph")
    p = membership.predict_proba(train)
    assert np.allclose(p.sum(axis=1), 1)
    assert np.allclose(p.sum(axis=0), [150, 150], atol=1e-8)
    before = membership.transform.named_steps["scale"].mean_.copy()
    future = train.iloc[:2].copy()
    future["style_speed_mph"] = 200.0
    future["bf"] = -999
    membership.predict_proba(future)
    assert np.array_equal(before, membership.transform.named_steps["scale"].mean_)
    assert set(membership.append_memberships(train)) >= {"archetype_p0", "archetype_p1"}
    assert membership.selection["candidates"][0]["medianAdjustedRandIndex"] == 1


def test_failed_cluster_gate_does_not_force_assignment():
    with threadpool_limits(limits=1):
        membership = subject.ArchetypeMembership(cluster_counts=(2,), minimum_pitchers=31).fit(cluster_frame())
    assert membership.supported is False and membership.selected_k is None
    assert "DISTINCT_PITCHER_SUPPORT_BELOW_MINIMUM" in membership.candidate_summary[0]["failureReasons"]
    with pytest.raises(subject.UnsupportedArchetypes):
        membership.predict_proba(cluster_frame())


def test_clusters_require_whole_unique_starts_and_supported_profiles():
    x = cluster_frame()
    x.loc[1, "startId"] = x.loc[0, "startId"]
    with pytest.raises(ValueError, match="UNIQUE_IDENTIFIED"):
        subject.ArchetypeMembership().fit(x)
    x = cluster_frame()
    x.loc[0, "profileSupported"] = False
    with pytest.raises(ValueError, match="SUPPORTED_PRIOR"):
        subject.ArchetypeMembership().fit(x)


def test_nonfinite_probabilities_and_impossible_bf_fail_closed():
    with pytest.raises(ValueError, match="INVALID_COMPETING"):
        subject.pregame_bf_distribution(constant_model((np.nan, 0.2, 0.1)), frame(1))
    with pytest.raises(ValueError, match="NONNEGATIVE_INTEGER"):
        subject.conditional_removal_probability(
            constant_model(), frame(1).assign(bf=1.5), game_active=[True], starter_active=[True])
