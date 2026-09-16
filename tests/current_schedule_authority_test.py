"""Focused, provider-free tests for current Statcast schedule authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.bronze_acquisition.schedule_authority import (
    SCHEDULE_AUTHORITY_CONTRACT,
    ScheduleAuthorityError,
    acquire_schedule_authority,
    parse_schedule_payload,
    schedule_url,
)
from tools.bronze_acquisition.safety import BronzeBoundaryError


def _game(
    game_pk: int,
    detailed_state: str,
    *,
    official_date: str = "2026-08-27",
    away_id: int = 110,
    home_id: int = 147,
) -> dict:
    return {
        "gamePk": game_pk,
        "officialDate": official_date,
        "gameType": "R",
        "status": {"detailedState": detailed_state},
        "teams": {
            "away": {"team": {"id": away_id, "name": f"Away {away_id}"}},
            "home": {"team": {"id": home_id, "name": f"Home {home_id}"}},
        },
    }


def _payload(*games: dict, date: str = "2026-08-27") -> bytes:
    return json.dumps({"dates": [{"date": date, "games": list(games)}]}).encode("utf-8")


class _FakeDownloader:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.calls: list[str] = []

    def __call__(self, url: str, dest: Path, **_kwargs) -> dict:
        self.calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.raw)
        digest = hashlib.sha256(self.raw).hexdigest()
        return {"sha256": digest, "bytes": len(self.raw), "reused": False}


def test_schedule_url_is_regular_and_cutoff_bounded():
    url = schedule_url("2026-08-26", "2026-08-27")
    assert "sportId=1" in url
    assert "gameTypes=R" in url
    assert "startDate=2026-08-26" in url
    assert "endDate=2026-08-27" in url
    with pytest.raises(BronzeBoundaryError):
        schedule_url("2026-08-27", "2026-08-28")
    with pytest.raises(BronzeBoundaryError):
        schedule_url("2026-08-27", "2026-08-26")


def test_only_final_and_completed_early_are_accepted():
    raw = _payload(
        _game(10, "Live"),
        _game(11, "Final"),
        _game(12, "Postponed"),
        _game(13, "Completed Early"),
        _game(14, "Cancelled"),
        _game(15, "Suspended"),
    )
    parsed = parse_schedule_payload(raw, start_date="2026-08-27", end_date="2026-08-27")
    assert [game["gamePk"] for game in parsed["completedGames"]] == [11, 13]
    assert [game["gamePk"] for game in parsed["excludedGames"]] == [10, 12, 14, 15]
    assert {game["detailedState"] for game in parsed["completedGames"]} == {"Final", "Completed Early"}


def test_postponed_makeup_status_progression_uses_completed_identity():
    postponed = _game(778443, "Postponed", official_date="2025-04-06")
    postponed["status"].update(
        {
            "abstractGameState": "Final",
            "codedGameState": "D",
            "statusCode": "DR",
            "reason": "Rain",
        }
    )
    final = _game(778443, "Final", official_date="2025-04-06")
    final["status"].update(
        {
            "abstractGameState": "Final",
            "codedGameState": "F",
            "statusCode": "F",
        }
    )
    raw = json.dumps(
        {
            "dates": [
                {"date": "2025-04-05", "games": [postponed]},
                {"date": "2025-04-06", "games": [final]},
            ]
        }
    ).encode("utf-8")
    parsed = parse_schedule_payload(raw, start_date="2025-04-05", end_date="2025-04-06")
    assert parsed["excludedGames"] == []
    assert len(parsed["completedGames"]) == 1
    accepted = parsed["completedGames"][0]
    assert accepted["gamePk"] == 778443
    assert accepted["gameDate"] == "2025-04-06"
    assert accepted["detailedState"] == "Final"
    assert accepted["awayTeamId"] == 110 and accepted["homeTeamId"] == 147
    assert accepted["scheduleObservations"] == [
        {
            "abstractGameState": "Final",
            "codedGameState": "D",
            "detailedState": "Postponed",
            "officialDate": "2025-04-06",
            "reason": "Rain",
            "scheduleDate": "2025-04-05",
            "statusCode": "DR",
            "providerGameDate": None,
        },
        {
            "abstractGameState": "Final",
            "codedGameState": "F",
            "detailedState": "Final",
            "officialDate": "2025-04-06",
            "reason": None,
            "scheduleDate": "2025-04-06",
            "statusCode": "F",
            "providerGameDate": None,
        },
    ]


def test_future_reschedule_is_preserved_but_never_admitted(tmp_path):
    postponed = _game(823543, "Postponed", official_date="2026-09-22")
    postponed["gameDate"] = "2026-05-23T17:35:00Z"
    postponed["status"].update(
        {
            "abstractGameState": "Final",
            "codedGameState": "D",
            "statusCode": "DR",
            "reason": "Rain",
        }
    )
    parsed = parse_schedule_payload(
        _payload(postponed, date="2026-05-23"),
        start_date="2026-03-25",
        end_date="2026-08-27",
    )
    assert parsed["completedGames"] == []
    assert len(parsed["excludedGames"]) == 1
    excluded = parsed["excludedGames"][0]
    assert excluded["gamePk"] == 823543
    assert excluded["gameDate"] == "2026-09-22"
    assert excluded["detailedState"] == "Postponed"
    assert excluded["authorityExclusionReason"] == "OFFICIAL_DATE_AFTER_AUTHORIZED_CUTOFF"
    assert excluded["scheduleObservations"] == [
        {
            "abstractGameState": "Final",
            "codedGameState": "D",
            "detailedState": "Postponed",
            "officialDate": "2026-09-22",
            "providerGameDate": "2026-05-23T17:35:00Z",
            "reason": "Rain",
            "scheduleDate": "2026-05-23",
            "statusCode": "DR",
        }
    ]

    later_final = _game(823543, "Final", official_date="2026-09-22")
    parsed_final = parse_schedule_payload(
        _payload(later_final, date="2026-05-23"),
        start_date="2026-03-25",
        end_date="2026-08-27",
    )
    assert parsed_final["completedGames"] == []
    assert parsed_final["excludedGames"][0]["authorityExclusionReason"] == (
        "OFFICIAL_DATE_AFTER_AUTHORIZED_CUTOFF"
    )

    acquired = acquire_schedule_authority(
        tmp_path,
        start_date="2026-03-25",
        end_date="2026-08-27",
        downloader=_FakeDownloader(_payload(postponed, date="2026-05-23")),
    )
    manifest = json.loads(Path(acquired["manifestPath"]).read_text(encoding="utf-8"))
    assert acquired["completedGameCount"] == 0 and acquired["excludedGameCount"] == 1
    assert manifest["completedGames"] == []
    assert manifest["excludedGames"][0]["gamePk"] == 823543
    assert manifest["excludedGames"][0]["authorityExclusionReason"] == (
        "OFFICIAL_DATE_AFTER_AUTHORIZED_CUTOFF"
    )


def test_acquisition_preserves_raw_sha_and_is_resumable(tmp_path):
    raw = _payload(
        _game(823014, "Final"),
        _game(822694, "Final"),
        _game(823503, "Completed Early"),
        _game(999999, "Postponed"),
    )
    downloader = _FakeDownloader(raw)
    first = acquire_schedule_authority(
        tmp_path,
        start_date="2026-08-27",
        end_date="2026-08-27",
        downloader=downloader,
    )
    assert len(downloader.calls) == 1
    raw_path = Path(first["rawPath"])
    assert raw_path.read_bytes() == raw
    assert first["rawSha256"] == hashlib.sha256(raw).hexdigest()

    manifest_path = Path(first["manifestPath"])
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    assert manifest["manifestContract"] == SCHEDULE_AUTHORITY_CONTRACT
    assert [game["gamePk"] for game in manifest["completedGames"]] == [822694, 823014, 823503]
    assert [game["detailedState"] for game in manifest["completedGames"]] == [
        "Final",
        "Final",
        "Completed Early",
    ]
    assert [game["gamePk"] for game in manifest["excludedGames"]] == [999999]
    assert manifest["seasonCounts"] == [
        {
            "completedGameCount": 3,
            "excludedGameCount": 1,
            "scheduledGameCount": 4,
            "season": 2026,
            "statusCounts": {"Completed Early": 1, "Final": 2, "Postponed": 1},
        }
    ]
    assert manifest["snapshots"][0]["rawSha256"] == first["rawSha256"]

    def _must_not_call_provider(*_args, **_kwargs):
        raise AssertionError("resume must not call a provider")

    second = acquire_schedule_authority(
        tmp_path,
        start_date="2026-08-27",
        end_date="2026-08-27",
        downloader=_must_not_call_provider,
    )
    assert second["manifestSha256"] == first["manifestSha256"]
    assert manifest_path.read_bytes() == manifest_bytes


def test_interrupted_raw_artifact_is_adopted_without_provider_call(tmp_path):
    raw = _payload(_game(823014, "Final"))
    raw_path = (
        tmp_path
        / "mlb-stats-api"
        / "regular"
        / "start=2026-08-27"
        / "end=2026-08-27"
        / "schedule.json"
    )
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(raw)

    def _must_not_call_provider(*_args, **_kwargs):
        raise AssertionError("existing raw evidence must be resumed locally")

    result = acquire_schedule_authority(
        tmp_path,
        start_date="2026-08-27",
        end_date="2026-08-27",
        downloader=_must_not_call_provider,
    )
    assert result["completedGameCount"] == 1
    assert result["rawSha256"] == hashlib.sha256(raw).hexdigest()


def test_recorded_raw_tamper_fails_closed(tmp_path):
    raw = _payload(_game(823014, "Final"))
    result = acquire_schedule_authority(
        tmp_path,
        start_date="2026-08-27",
        end_date="2026-08-27",
        downloader=_FakeDownloader(raw),
    )
    Path(result["rawPath"]).write_bytes(_payload(_game(823014, "Postponed")))
    with pytest.raises(ScheduleAuthorityError, match="SHA mismatch"):
        acquire_schedule_authority(
            tmp_path,
            start_date="2026-08-27",
            end_date="2026-08-27",
            downloader=lambda *_args, **_kwargs: pytest.fail("must not redownload over tampered bytes"),
        )


def test_two_nonoverlapping_season_snapshots_are_aggregated(tmp_path):
    first = _FakeDownloader(
        _payload(_game(700001, "Final", official_date="2025-09-28"), date="2025-09-28")
    )
    acquire_schedule_authority(
        tmp_path,
        start_date="2025-09-28",
        end_date="2025-09-28",
        downloader=first,
    )
    second = _FakeDownloader(_payload(_game(800001, "Final"), date="2026-08-27"))
    result = acquire_schedule_authority(
        tmp_path,
        start_date="2026-08-27",
        end_date="2026-08-27",
        downloader=second,
    )
    manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
    assert manifest["snapshotCount"] == 2
    assert [game["gamePk"] for game in manifest["completedGames"]] == [700001, 800001]
    assert [(item["season"], item["completedGameCount"]) for item in manifest["seasonCounts"]] == [
        (2025, 1),
        (2026, 1),
    ]


def test_overlap_and_conflicting_duplicate_fail_closed(tmp_path):
    acquire_schedule_authority(
        tmp_path,
        start_date="2026-08-26",
        end_date="2026-08-27",
        downloader=_FakeDownloader(_payload(_game(823014, "Final"))),
    )
    with pytest.raises(ScheduleAuthorityError, match="overlaps immutable snapshot"):
        acquire_schedule_authority(
            tmp_path,
            start_date="2026-08-27",
            end_date="2026-08-27",
            downloader=_FakeDownloader(_payload(_game(823014, "Final"))),
        )

    conflict = _payload(
        _game(823014, "Final", home_id=147),
        _game(823014, "Final", home_id=111),
    )
    with pytest.raises(ScheduleAuthorityError, match="conflicting duplicate"):
        parse_schedule_payload(conflict, start_date="2026-08-27", end_date="2026-08-27")


def test_non_regular_response_is_rejected():
    game = _game(823014, "Final")
    game["gameType"] = "P"
    with pytest.raises(ScheduleAuthorityError, match="non-regular"):
        parse_schedule_payload(
            _payload(game), start_date="2026-08-27", end_date="2026-08-27"
        )


def test_missing_dates_array_is_rejected():
    with pytest.raises(ScheduleAuthorityError, match="dates array"):
        parse_schedule_payload(
            b"{}", start_date="2026-08-27", end_date="2026-08-27"
        )
