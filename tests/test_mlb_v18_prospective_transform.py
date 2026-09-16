from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

from server.sports_current_statcast.mlb_v18_current_slate import load_contract, verify_accepted_reload
from server.sports_current_statcast.mlb_v18_daily_slate import PARENT_BUNDLE_SHA256
from server.sports_current_statcast.mlb_v18_prospective_transform import (
    ATTR, ProspectiveAuthorityError, ProspectiveFrameAuthority, authorize_frame,
    semantic_code_compatible, wrap_prospective_pipeline,
)


def test_accepted_dev_fixture_and_explicit_prospective_parity_with_closed_oot():
    """Synthetic future-date parity only; never a published current forecast."""
    root = Path(__file__).resolve().parents[1]
    contract = load_contract()
    assert verify_accepted_reload(contract)["bitwiseEqual"] is True
    model = joblib.load(root / f"outputs/mlb-v18-whole-game-challenger/sha256/{PARENT_BUNDLE_SHA256}/executable/v18-pa-fold5.joblib")
    original = pd.read_parquet(contract["artifacts"]["matchedOof"]["path"], filters=[("foldNumber", "=", 5)]).head(32)
    raw = pd.read_parquet(contract["artifacts"]["rawDevelopment"]["path"],
        filters=[("canonicalPaId", "in", original.canonicalPaId.tolist())], columns=contract["rawFeatureColumns"])
    raw = raw.set_index("canonicalPaId", drop=False).loc[original.canonicalPaId, contract["rawFeatureColumns"]]
    assert len(raw) == 32 and raw.game_date.max() <= "2026-08-06"
    now = datetime.now(timezone.utc)
    kickoff = now + timedelta(hours=2)
    authority = ProspectiveFrameAuthority("PROSPECTIVE_NUMERICAL_FIXTURE_ONLY", kickoff.date().isoformat(),
        (now-timedelta(minutes=1)).isoformat(), kickoff.isoformat(),
        contract["artifacts"]["rawDevelopment"]["sha256"], now.isoformat(), "UTC")
    future = raw.copy()
    future["game_date"] = authority.game_date
    if "canonicalGameId" in future:
        future["canonicalGameId"] = authority.event_id
    with pytest.raises(ValueError):
        model.preprocessor.transform_frame(future)
    wrapped = wrap_prospective_pipeline(model, authority)
    with threadpool_limits(limits=4):
        dev_values = model.preprocessor.transform(raw)
        current_values = wrapped.preprocessor.transform(future)
        assert np.array_equal(np.asarray(dev_values), np.asarray(current_values), equal_nan=True)
        assert np.array_equal(model.predict_proba(raw), wrapped.predict_proba(future))
    assert ATTR not in raw.attrs and ATTR not in future.attrs
    assert "context_inning" in model.preprocessor.ordered_features
    with pytest.raises(ProspectiveAuthorityError):
        authorize_frame(future.assign(target=1), authority)
    with pytest.raises(ProspectiveAuthorityError):
        authorize_frame(future.assign(game_date="2026-08-20"), authority)
    with pytest.raises(ProspectiveAuthorityError):
        authorize_frame(future, replace(authority, evidence_cutoff_utc=kickoff.isoformat()))
    with pytest.raises(ProspectiveAuthorityError):
        authorize_frame(future, replace(authority, kickoff_utc=(now-timedelta(seconds=1)).isoformat()))
    from server.sports_current_statcast.stage3_semantic_treatment import _dates, SemanticTreatmentError
    with pytest.raises(SemanticTreatmentError):
        _dates(authorize_frame(future, authority), training_end="2026-08-13")
    assert semantic_code_compatible("unknown", "unknown") is False
