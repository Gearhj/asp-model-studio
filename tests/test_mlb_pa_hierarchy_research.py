"""Focused synthetic tests; no baseball training population or performance claim."""
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from server.sports_current_statcast.mlb_pa_hierarchy_research import (
    CLASS_ORDER, OUT_INDICES, NON_OUT_INDICES, assemble_probabilities,
    fit_hierarchies, loss_decomposition, persist_and_verify, load_verified,
)


def fixture():
    n = 96
    x = pd.DataFrame({"a": np.linspace(-1, 1, n), "b": np.sin(np.arange(n)), "c": np.arange(n) % 3})
    y = np.arange(n) % 8
    authority = {"candidateFitAuthorized": True, "scope": "SYNTHETIC_FIXTURE_ONLY",
        "cohortId": "SYNTHETIC_BALANCED_96", "trainingInformationCutoffExclusive": "2024-01-01"}
    return x, y, authority


def test_soft_lossless_mapping_and_edge_probabilities():
    q = np.array([0, 0.25, 1.0])
    out = np.tile([0.3, 0.7], (3, 1))
    non = np.tile(np.arange(1, 7)/21, (3, 1))
    p = assemble_probabilities(q, out, non)
    np.testing.assert_allclose(p.sum(axis=1), 1, atol=1e-15)
    np.testing.assert_array_equal(p[:, 0], q*0.3)
    np.testing.assert_array_equal(p[:, 6], q*0.7)
    np.testing.assert_array_equal(p[:, 2], (1-q)*2/21)
    assert CLASS_ORDER[1] == "WALK_HBP_CI" and CLASS_ORDER[7] == "OTHER_REACH"
    with pytest.raises(ValueError):
        assemble_probabilities(q, out, non[:, :5])


def test_root_plus_conditional_loss_identity_and_scoring_copy():
    p = np.eye(8)*0.6+0.05
    original = p.copy()
    y = np.arange(8)
    result = loss_decomposition(p, y)
    assert result["eightClassLogLoss"] == pytest.approx(result["rootLogLoss"]+result["conditionalHeadLogLoss"])
    assert result["conditionalHeadLogLoss"] == pytest.approx(
        result["outHeadAllPaContribution"]+result["nonOutHeadAllPaContribution"])
    assert result["outRows"] == 2 and result["nonOutRows"] == 6
    np.testing.assert_array_equal(p, original)
    zero_result = loss_decomposition(np.eye(8), np.roll(y, 1))
    assert np.isfinite(zero_result["eightClassLogLoss"])
    assert zero_result["maximumDecompositionDifference"] < 1e-12


def test_shared_root_frozen_features_and_executable_reload(tmp_path):
    x, y, authority = fixture()
    b, c = fit_hierarchies(x, y, frozen_preprocessor=None,
        estimator_template=LogisticRegression(C=0.5, max_iter=100, random_state=7), training_authority=authority)
    assert b.root is c.root
    pb, pc = b.predict_proba(x), c.predict_proba(x)
    np.testing.assert_allclose(pb[:, OUT_INDICES].sum(axis=1), pc[:, OUT_INDICES].sum(axis=1), atol=1e-15)
    np.testing.assert_allclose(pb[:, NON_OUT_INDICES]/pb[:, NON_OUT_INDICES].sum(axis=1)[:, None],
        np.tile(b.non_out_head.frequency, (len(x), 1)), atol=1e-15)
    for model in (b, c):
        ref = persist_and_verify(model, x.iloc[:16], tmp_path/model.mode)
        assert ref["mismatchedValues"] == 0 and ref["refitsDuringReload"] == 0
        assert ref["metadata"]["fitAccounting"]["actualEstimatorFits"] == 3
        with pytest.raises(ValueError):
            load_verified(ref["path"], "0"*64)
        with pytest.raises(ValueError):
            model.predict_proba(x[["b", "a", "c"]])


def test_unapproved_timing_fails_before_fit_and_absent_branch_is_explicit():
    x, y, authority = fixture()
    with pytest.raises(ValueError):
        fit_hierarchies(x, y, frozen_preprocessor=None, estimator_template=LogisticRegression(),
            training_authority={**authority, "candidateFitAuthorized": False})
    b, c = fit_hierarchies(x, np.zeros(len(x), dtype=int), frozen_preprocessor=None,
        estimator_template=LogisticRegression(), training_authority=authority)
    assert c.fit_accounting["actualEstimatorFits"] == 0
    assert c.non_out_head.estimator is None and c.non_out_head.counts.sum() == 0
    for model in (b, c):
        p = model.predict_proba(x)
        assert (p > 0).all()
        np.testing.assert_allclose(p.sum(axis=1), 1, atol=1e-15)
