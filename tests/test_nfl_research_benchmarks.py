import numpy as np
import pandas as pd
import pytest

from server.sports_nfl_m1.research_benchmarks import conditional_home, no_vig_home, timestamp_matched_quotes


def test_two_way_no_vig_preserves_original_tie_forecast():
    tie = np.array([.1])
    assert conditional_home(np.array([.3]), tie, np.array([.6])) == pytest.approx([2/3])
    assert tie == pytest.approx([.1])
    assert no_vig_home(np.array([-110]), np.array([-110])) == pytest.approx([.5])
    with pytest.raises(ValueError):
        no_vig_home(np.array([0]), np.array([100]))


def test_quotes_use_original_timezone_and_cutoff_not_export_time():
    forecasts = pd.DataFrame([{"eventId": "g", "forecastCutoffUtc": "2024-09-08T16:00:00Z", "scheduledStartUtc": "2024-09-08T17:00:00Z"}])
    quotes = pd.DataFrame([{"eventId": "g", "bookmaker": "test", "observedAtUtc": stamp, "homeMoneyline": -110, "awayMoneyline": -110, "settlementContract": "FULL_GAME_INCLUDING_OT_TIE_VOID"} for stamp in ("2024-09-08T15:00:00Z", "2024-09-08T16:01:00Z", "2024-09-08T15:30:00")])
    result, reasons = timestamp_matched_quotes(quotes, forecasts)
    assert len(result) == 1 and result.quoteAgeSeconds.iloc[0] == 3600
    assert reasons == {"INCLUDED": 1, "QUOTE_AFTER_CUTOFF": 1, "QUOTE_TIME_UNAVAILABLE": 1}
