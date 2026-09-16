from pathlib import Path
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from server.sports_current_statcast.mlb_v18_current_sources import (
    CurrentSourceError, SourceRequestTelemetry, _read_isolated_object,
    acquire_free_daily_source, acquire_schedule_identity_projection, safe_day,
)


def test_sealed_and_current_day_acquisition_fail_before_network():
    telemetry = SourceRequestTelemetry()
    with patch("server.sports_current_statcast.mlb_v18_current_sources.urlopen") as network:
        with pytest.raises(CurrentSourceError, match="FINAL_OOT_SEALED"):
            acquire_free_daily_source("2026-08-20", family="STATCAST", allow_free_network=True,
                                      request_telemetry=telemetry)
        with pytest.raises(CurrentSourceError, match="Target-date"):
            safe_day("2026-09-10", before="2026-09-10")
        preview = acquire_free_daily_source("2026-09-09", family="STATCAST", request_telemetry=telemetry)
        assert preview["status"] == "FREE_SOURCE_REQUEST_NOT_EXECUTED"
        network.assert_not_called()
        assert telemetry.snapshot()["requestAttemptCount"] == 0


def test_actual_request_telemetry_includes_failed_daily_and_projected_schedule_calls():
    telemetry = SourceRequestTelemetry()
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.headers = {"Content-Type": "application/json"}
    response.read.return_value = b'{"dates":[]}'
    with patch("server.sports_current_statcast.mlb_v18_current_sources.urlopen", side_effect=[
        response, HTTPError("https://statsapi.mlb.com", 503, "private-error-detail", None, None),
        TimeoutError("private-error-detail"),
    ]) as network, patch("server.sports_current_statcast.mlb_v18_current_sources._store",
                          return_value={"sha256": "a" * 64, "path": "unused", "bytes": 12}):
        acquire_free_daily_source("2026-09-09", family="SCHEDULE", allow_free_network=True,
                                  request_telemetry=telemetry)
        with pytest.raises(HTTPError):
            acquire_schedule_identity_projection(start="2026-03-25", through="2026-09-10",
                                                  allow_free_network=True, request_telemetry=telemetry)
        with pytest.raises(TimeoutError):
            acquire_free_daily_source("2026-09-09", family="STATCAST", allow_free_network=True,
                                      request_telemetry=telemetry)
        assert network.call_count == 3
    summary = telemetry.snapshot()
    assert summary["requestAttemptCount"] == 3
    assert summary["completedRequestCount"] == 1
    assert summary["failedRequestCount"] == 2
    assert summary["inFlightRequestCount"] == 0
    assert {k: summary["byFamily"][k]["requestAttemptCount"]
            for k in ("SCHEDULE", "STATCAST", "SCHEDULE_IDENTITIES_ONLY")} == {
        "SCHEDULE": 1, "STATCAST": 1, "SCHEDULE_IDENTITIES_ONLY": 1,
    }
    assert summary["attempts"][1]["httpStatus"] == 503
    assert "private-error-detail" not in json.dumps(summary)
    assert summary["sourceCostUsd"] == summary["paidProviderCalls"] == summary["automaticRetriesAdded"] == 0


def test_cached_collector_attempt_records_zero_actual_requests():
    from scripts import acquire_mlb_v18_current_sources as collector

    schedule = {"startDate": "2026-03-25", "throughDate": "2026-09-10", "observedAt": "2026-09-10T10:00:00Z",
                "raw": {"sha256": "schedule-cached"}}
    cached = [{"day": "2026-09-09", "family": family, "raw": {"sha256": family}}
              for family in ("SCHEDULE", "STATCAST")]
    plan = {"requests": [], "cachedReceipts": cached, "scheduleReceipts": [schedule],
            "correctionDates": [], "pendingCatchupDates": []}
    with patch.object(collector, "incremental_plan", return_value=plan), \
            patch.object(collector, "_store", return_value={"sha256": "new-attempt"}) as store, \
            patch("server.sports_current_statcast.mlb_v18_current_sources.urlopen") as network, \
            patch("sys.argv", ["acquire", "--start", "2026-09-09", "--through", "2026-09-09",
                               "--schedule-through", "2026-09-10", "--allow-free-network",
                               "--reuse-schedule-projection", "--correction-days", "0"]):
        collector.main()
    attempt = json.loads(store.call_args.args[0])
    assert attempt["requestTelemetry"]["requestAttemptCount"] == 0
    assert attempt["receipts"] == cached
    assert attempt["scheduleIdentityReceipt"] == schedule
    network.assert_not_called()


def test_mixed_oot_rowgroup_is_refused_before_payload_hash_or_read():
    root = Path(__file__).resolve().parent
    footer = MagicMock()
    footer.schema_arrow.names = ["gameDate"]
    footer.num_row_groups = 1
    stats = footer.metadata.row_group.return_value.column.return_value.statistics
    stats.has_min_max = True
    stats.min, stats.max = "2026-08-13", "2026-08-14"
    with patch("server.sports_current_statcast.mlb_v18_current_sources.pq.ParquetFile", return_value=footer), \
            patch.object(Path, "read_bytes", side_effect=AssertionError("Payload must stay closed")):
        with pytest.raises(CurrentSourceError, match="MIXED_OR_UNPROVEN_SOURCE_ROW_GROUP"):
            _read_isolated_object(root, {"relativePath": "not-opened.parquet", "sha256": "0" * 64, "byteCount": 0}, "2026-08-13")
        footer.read.assert_not_called()
