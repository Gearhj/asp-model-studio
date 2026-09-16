"""Focused pre-date history and uncertainty/mean separation protections."""
import io

import joblib
import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast.mlb_v19_models import (
    CandidatePipeline, DOMAINS, K, SemanticPriors, prior_counts,
)


class FixtureEncoder:
    def transform(self, values):
        return values.to_numpy(dtype=float)


class FixtureFrozenPreprocessor:
    encoder = FixtureEncoder()

    def transform_frame(self, rows):
        return rows[["fixture_numeric"]]


class FixtureEstimator:
    classes_ = np.arange(K)

    def predict_proba(self, values):
        scores = np.exp(.01 * values.sum(axis=1, keepdims=True) * np.arange(K)[None, :])
        return scores / scores.sum(axis=1, keepdims=True)


def test_current_and_carryover_counts_exclude_entire_query_date_and_future():
    history = pd.DataFrame({
        "canonicalPaId": ["a", "b", "c", "d"], "player": ["p"] * 4,
        "game_date": ["2024-05-01", "2024-05-02", "2024-05-03", "2023-06-01"],
        "observedClassIndex": [0, 1, 2, 3],
    })
    query = pd.DataFrame({"player": ["p", "absent"], "game_date": ["2024-05-02"] * 2})
    current, previous = prior_counts(history, query, "player")
    assert current[0].tolist() == [1., 0., 0., 0., 0., 0., 0., 0.]
    assert previous[0, 0].tolist() == [0., 0., 0., 1., 0., 0., 0., 0.]
    assert current[1].sum() == previous[1].sum() == 0
    changed = history.copy()
    changed.loc[changed.game_date >= "2024-05-02", "observedClassIndex"] = 7
    actual = prior_counts(changed.sample(frac=1, random_state=10), query, "player")
    np.testing.assert_array_equal(actual[0], current)
    np.testing.assert_array_equal(actual[1], previous)


def test_uncertainty_only_override_cannot_change_means_and_pipeline_reloads_exactly():
    history = pd.DataFrame({
        "canonicalPaId": ["past"], "game_date": ["2024-05-01"], "observedClassIndex": [0],
        "batterCanonicalPlayerId": ["b"], "pitcherCanonicalPlayerId": ["p"],
        "battingTeamId": ["a"], "fieldingTeamId": ["h"],
        "matchup_batter_bats_left": [0], "matchup_batter_bats_switch": [0],
        "matchup_batter_hand_missing": [0], "matchup_pitcher_hand_missing": [0],
        "matchup_pitcher_throws_left": [0], "fixture_numeric": [1.],
    })
    query = history.copy()
    query["canonicalPaId"] = "query"
    query["game_date"] = "2024-05-02"
    semantic = SemanticPriors()
    semantic.parameters = {
        domain: {"alpha": 100., "decay": .5, "populations": {group: np.full(K, 1 / K) for group in range(4)}}
        for domain in DOMAINS
    }
    means, uncertainty = semantic.transform(history, query)
    semantic.feature_names = list(means)
    semantic.uncertainty_names = list(uncertainty)
    pipeline = CandidatePipeline(FixtureFrozenPreprocessor(), semantic, None, FixtureEstimator(),
                                 "SEMANTIC_HGB", ["fixture_numeric", *semantic.feature_names], [])
    expected = pipeline.predict_proba(query, history)
    for override in (np.zeros((1, 4)), np.full((1, 4), 1e12), {"uncertainty": "unavailable"}):
        np.testing.assert_array_equal(pipeline.predict_proba(query, history, uncertainty_only_override=override), expected)
    buffer = io.BytesIO()
    joblib.dump(pipeline, buffer)
    buffer.seek(0)
    reloaded = joblib.load(buffer)
    np.testing.assert_array_equal(reloaded.predict_proba(query, history), expected)


def test_empty_missing_identity_or_stale_history_fails_before_numerical_inference():
    pipeline = CandidatePipeline(None, None, None, None, "SEMANTIC_HGB", [], [])
    query = pd.DataFrame({"game_date": ["2024-05-05"]})
    with pytest.raises(ValueError, match="SOURCE_FAILURE_MISSING_HISTORY_OR_ENTITY_IDENTITY"):
        pipeline.matrix(query, pd.DataFrame())
    history = pd.DataFrame({"game_date": ["2024-05-04"],
                            **{name: ["known"] for name in DOMAINS.values()}})
    history["batterCanonicalPlayerId"] = None
    with pytest.raises(ValueError, match="SOURCE_FAILURE_MISSING_HISTORY_OR_ENTITY_IDENTITY"):
        pipeline.matrix(query, history)
    history["batterCanonicalPlayerId"] = "known"
    history["game_date"] = "2024-05-01"
    with pytest.raises(ValueError, match="SOURCE_GAP_HISTORY_NOT_CURRENT_THROUGH_PRIOR_DATE"):
        pipeline.matrix(query, history)
