import numpy as np
import pandas as pd

from server.sports_current_statcast.mlb_duration_research_adapter import removal_probability, apply_removal_draws


def test_no_game_end_draw_no_removed_starter_reentry_and_no_zero_bf_extrapolation():
    class Fixture:
        feature_order = ("bf",)
        seen = None

        def predict_proba(self, frame, calibrated=True):
            self.seen = frame.index.tolist()
            return np.tile([0.5, 0.3, 0.2], (len(frame), 1))
    model = Fixture()
    frame = pd.DataFrame({"bf": [12, 12, 12, 0]})
    games, active = [True, False, True, True], [True, True, False, True]
    p = removal_probability(model, frame, game_active=games, starter_active=active)
    assert model.seen == [0]
    assert np.allclose(p, [0.375, 0, 0, 0])
    next_active = apply_removal_draws(active, games, p, [0.1] * 4)
    assert next_active.tolist() == [False, True, False, True]
    assert not apply_removal_draws(next_active, games, p, [0.1] * 4)[0]
