import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast.mlb_rf_operationalization import (
    PROBABILITIES, publication_gate, verify_saved_rf_predictions,
)


def test_saved_prediction_identity_is_not_executable_reproduction():
    original = pd.DataFrame({"canonicalPaId": ["p1", "p2"], "canonicalGameId": ["g", "g"],
                             "foldNumber": [1, 1], "observedClassIndex": [0, 1],
                             **{name: [.125, .125] for name in PROBABILITIES}})
    matched = original.rename(columns={name: "rf_" + name for name in PROBABILITIES})
    checked = verify_saved_rf_predictions(matched, original.iloc[::-1])
    assert checked["bitwiseEqual"] and not checked["estimatorReproductionPassed"]
    assert not publication_gate(estimator_reproduction=checked, prospective_games=15)["publicationAllowed"]
    changed = matched.copy()
    changed.loc[0, "rf_" + PROBABILITIES[0]] = np.nextafter(.125, 1.)
    with pytest.raises(ValueError, match="probabilities differ"):
        verify_saved_rf_predictions(changed, original)
    wrong_game = matched.copy()
    wrong_game.loc[0, "canonicalGameId"] = "another-game"
    with pytest.raises(ValueError, match="canonicalGameId differs"):
        verify_saved_rf_predictions(wrong_game, original)
