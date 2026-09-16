"""Read-only checks; archived OOF values never stand in for a frozen estimator."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from server.sports_modeling.metrics import PA_CLASS_ORDER

PROBABILITIES = [f"probability_{name}" for name in PA_CLASS_ORDER]
KEYS = ["canonicalGameId", "foldNumber", "observedClassIndex"]


def verify_saved_rf_predictions(matched: pd.DataFrame, original: pd.DataFrame) -> dict:
    """Verify archival reuse only, on exact PA/game/fold/target identities."""
    for frame in (matched, original):
        if frame.canonicalPaId.isna().any() or frame.canonicalPaId.duplicated().any():
            raise ValueError("Missing or duplicate PA identity")
    if not matched.canonicalPaId.isin(original.canonicalPaId).all():
        raise ValueError("Matched population contains unknown RF PA identities")
    aligned = original.set_index("canonicalPaId").loc[matched.canonicalPaId].reset_index()
    for name in KEYS:
        if not np.array_equal(matched[name].to_numpy(), aligned[name].to_numpy()):
            raise ValueError(f"RF matched {name} differs")
    actual = np.ascontiguousarray(matched[["rf_" + x for x in PROBABILITIES]], dtype=np.float64)
    expected = np.ascontiguousarray(aligned[PROBABILITIES], dtype=np.float64)
    if not np.isfinite(actual).all() or not np.isfinite(expected).all():
        raise ValueError("Nonfinite RF probabilities")
    differences = actual.view(np.uint64) != expected.view(np.uint64)
    result = {
        "checkType": "SAVED_PREDICTION_IDENTITY_NOT_ESTIMATOR_REPRODUCTION",
        "originalRows": len(original), "matchedRows": len(matched),
        "matchedGames": int(matched.canonicalGameId.nunique()),
        "mismatchedProbabilityValues": int(differences.sum()),
        "maximumAbsoluteDifference": float(np.max(np.abs(actual - expected))),
        "bitwiseEqual": not bool(differences.any()),
        "matchedProbabilityBytesSha256": hashlib.sha256(actual.tobytes()).hexdigest(),
        "folds": [{"foldNumber": int(fold), "rows": len(rows),
                   "games": int(rows.canonicalGameId.nunique())}
                  for fold, rows in matched.groupby("foldNumber", sort=True)],
        "estimatorInferenceCalls": 0, "estimatorReproductionPassed": False,
    }
    if differences.any():
        raise ValueError(f"Saved RF probabilities differ: {result}")
    return result


def publication_gate(*, estimator_reproduction: dict, prospective_games: int) -> dict:
    """No archived-prediction or preprocessing-only success can unlock publication."""
    exact = (estimator_reproduction.get("status") == "EXACT_FROZEN_ESTIMATOR_REPRODUCED"
             and estimator_reproduction.get("estimatorInferenceCalls", 0) > 0
             and estimator_reproduction.get("matchedRows") == 494432
             and estimator_reproduction.get("mismatchedProbabilityValues") == 0
             and bool(estimator_reproduction.get("frozenEstimatorArtifactSha256"))
             and bool(estimator_reproduction.get("frozenPreprocessingArtifactSha256")))
    reasons = []
    if not exact:
        reasons.append("ORIGINAL_RF_EXECUTABLE_REPRODUCTION_NOT_ESTABLISHED")
    if prospective_games < 1:
        reasons.append("NO_VERIFIED_NEXT_SLATE_INPUTS")
    return {"publicationAllowed": not reasons, "reasons": reasons,
            "researchShadow": True, "promotionStatus": "NOT_PROMOTED",
            "wageringAuthority": False, "executionAllowedInAISP": False}
