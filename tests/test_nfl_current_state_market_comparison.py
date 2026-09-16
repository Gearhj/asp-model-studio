"""One regression: quote observation alone cannot bypass forecast availability."""
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from server.sports_nfl_m1 import current_state_market_comparison as market


def test_pending_is_idempotent_and_postsnapshot_quotes_never_enter_comparison():
    with tempfile.TemporaryDirectory(prefix="nfl-current-market-") as directory:
        root = Path(directory)
        def save(name, body):
            raw = json.dumps(body, sort_keys=True).encode()
            path = root / name
            path.write_bytes(raw)
            return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw)}
        forecast = save("forecast.json", {"forecastId": "model-only-immutable", "eventId": "2026_01_NE_SEA",
            "model": {"engineId": "NFL_CURRENT_STATE_RESIDUAL_V2", "modelVersion": "V2"},
            "homeTeam": {"teamId": "SEA"}, "awayTeam": {"teamId": "NE"},
            "forecastCreatedUtc": "2026-09-10T11:00:00Z", "forecastCutoffUtc": "2026-09-10T11:00:00Z",
            "scheduledStartUtc": "2026-09-10T12:00:00Z", "sourceCutoffUtc": "2026-09-09T00:36:00Z",
            "homeWinProbability": .5, "awayWinProbability": .48, "tieProbability": .02,
            "expectedHomeScore": 24., "expectedAwayScore": 23.})
        handoff = save("handoff.json", {"schemaVersion": "NFL_CURRENT_STATE_JOINT_DISTRIBUTION_HANDOFF_V2",
            "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "wageringAuthority": False,
            "executionAllowedInAISP": False, "forecasts": [forecast], "forecastCount": 1})
        quote = {"quoteId": "valid", "sourceSnapshotId": "snap", "eventId": "2026_01_NE_SEA", "homeTeamId": "SEA", "awayTeamId": "NE",
            "bookmaker": "synthetic-book", "marketType": "MONEYLINE", "observedAtUtc": "2026-09-10T10:59:00Z",
            "firstAvailableAtUtc": "2026-09-10T11:00:00Z", "settlementContract": "FULL_GAME_INCLUDING_OT_TIE_VOID",
            "homeMoneyline": -110, "awayMoneyline": 100}
        quotes = {"schemaVersion": "NFL_AISP_TIMED_QUOTE_SNAPSHOTS_V1", "exportId": "test-export", "sourceUseAuthority": {"basis": "synthetic fixture"},
            "exportedAtUtc": "2026-09-10T13:00:00Z", "snapshots": [quote,
                {**quote, "quoteId": "late-observation", "observedAtUtc": "2026-09-10T11:01:00Z", "firstAvailableAtUtc": "2026-09-10T11:01:00Z"},
                {**quote, "quoteId": "late-first-availability", "firstAvailableAtUtc": "2026-09-10T11:01:00Z"}]}
        with patch.object(market, "OUTPUTS_ROOT", root):
            pending = market.prepare_market_comparison(handoff, root / "comparison")
            repeated = market.prepare_market_comparison(handoff, root / "comparison")
            assert pending["comparison"] == repeated["comparison"] and repeated["reused"] is True
            body = json.loads(Path(pending["comparison"]["path"]).read_bytes())
            assert len(body["comparisons"]) == 3 and body["suppliedQuoteCount"] == 0
            assert all(row["status"] == "PENDING_COMPARISON" for row in body["comparisons"])
            joined = market.prepare_market_comparison(handoff, root / "comparison", quotes)
        body = json.loads(Path(joined["comparison"]["path"]).read_bytes())
        included = [row for row in body["comparisons"] if row.get("quoteId")]
        assert len(included) == 1 and included[0]["quoteId"] == "valid"
        assert included[0]["quoteAgeSeconds"] == 60
        rejected = {row["quoteId"]: row["disposition"] for row in body["quoteDecisions"]}
        assert rejected["late-observation"] == rejected["late-first-availability"] == "QUOTE_OR_FIRST_AVAILABILITY_AFTER_FORECAST_CUTOFF"
        assert body["modelOnlyForecasts"][0]["tieProbability"] == .02
        assert body["modelOnlyForecasts"][0]["marketInputsUsed"] is False
        assert body["evidenceClass"] == "OBSERVED_AS_OF"
        assert all(row["evidenceClass"] == "OBSERVED_AS_OF" for row in body["modelOnlyForecasts"] + body["comparisons"] + body["quoteDecisions"])
        assert body["modelOnlyForecasts"][0]["trainingEvidenceClass"] == "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
        assert body["exportContract"]["evidenceClass"] == "OBSERVED_AS_OF"
        assert body["quoteExport"]["evidenceClass"] == "OBSERVED_AS_OF"
        assert [market.horizon_bin(value) for value in (3599, 3600, 21600, 86400)] == ["<1h", "1-6h", "6-24h", ">=24h"]
