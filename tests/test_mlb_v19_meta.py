import joblib
import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast.mlb_regime_models import OffsetCorrection
from server.sports_current_statcast.mlb_v19_meta import (
    GLOBAL_ORDER, ConvexSimplex, MetaSystem, chronological_segments, fit_meta_system,
)


def frame():
    dates = pd.date_range("2025-04-01", periods=20)
    return pd.DataFrame({"canonicalPaId": ["pa" + str(i) for i in range(40)],
        "canonicalGameId": ["game" + str(i // 2) for i in range(40)],
        "game_date": np.repeat(dates.strftime("%Y-%m-%d"), 2), "foldNumber": 1,
        "observedClassIndex": np.arange(40) % 8,
        "batter_prior_missing": np.arange(40) % 2})


def test_meta_segments_preserve_games_dates_and_reject_future_outcomes():
    rows = frame()
    masks, receipt = chronological_segments(rows, 2)
    assert [int(mask.sum()) for mask in masks.values()] == [28, 6, 6]
    assert receipt["segments"]["specialistFit"]["endDate"] < receipt["segments"]["gateFit"]["startDate"]
    assert receipt["segments"]["gateFit"]["endDate"] < receipt["segments"]["temperatureFit"]["startDate"]
    for mask in masks.values():
        assert set(rows.loc[mask, "canonicalGameId"]).isdisjoint(rows.loc[~mask, "canonicalGameId"])
    with pytest.raises(ValueError, match="earlier OOF folds only"):
        chronological_segments(rows, 1)


def test_first_fold_identity_is_bitwise_and_has_no_fit_calls():
    rows = frame().iloc[:0]
    empty = {name: np.empty((0, 8)) for name in GLOBAL_ORDER}
    calls = []
    model = fit_meta_system(rows, empty, before_fold=1, selected_regimes=[],
        run_fit=lambda *args: calls.append(args))
    p = np.tile(np.array([.42, .23, .08, .08, .08, .04, .04, .03]), (40, 1))
    predictions = model.predict(frame(), {name: p for name in GLOBAL_ORDER}, calibrated=True)
    assert not calls
    assert model.receipt["actualMetaFits"] == 0
    assert len(model.receipt["targetOrder"]) == 8
    assert all(np.array_equal(matrix, p) for matrix in predictions.values())


def test_variable_width_convex_identity_and_masked_specialist_exact_reload(tmp_path):
    rows = frame()
    p = np.tile(np.array([.42, .23, .08, .08, .08, .04, .04, .03]), (len(rows), 1))
    global_gate = ConvexSimplex(tuple(GLOBAL_ORDER), np.array([.4, .2, .2, .1, .1]), {"syntheticFixture": True})
    specialist_gate = ConvexSimplex(("V18", "SPECIALIST:BATTER_ANNUAL_PRIOR_MISSING"), np.array([.7, .3]), {"syntheticFixture": True})
    expert = OffsetCorrection(np.array([[.08, -.04, -.04, 0, 0, 0, 0, 0]]), {"syntheticFixture": True})
    model = MetaSystem(3, global_gate, specialist_gate, {"BATTER_ANNUAL_PRIOR_MISSING": expert})
    expected = model.predict(rows, {name: p for name in GLOBAL_ORDER})
    outside = rows.batter_prior_missing.eq(0).to_numpy()
    assert np.array_equal(expected["SPECIALIST_MIXTURE"][outside], p[outside])
    assert np.array_equal(expected["GLOBAL_ENSEMBLE"], p)
    path = tmp_path / "synthetic-meta.joblib"
    joblib.dump(model, path)
    replay = joblib.load(path).predict(rows.assign(observedClassIndex=7, context_inning=99), {name: p for name in GLOBAL_ORDER})
    assert all(np.array_equal(expected[name], replay[name]) for name in expected)
    with pytest.raises(ValueError, match="branch contract"):
        global_gate.predict({"V18": p})
