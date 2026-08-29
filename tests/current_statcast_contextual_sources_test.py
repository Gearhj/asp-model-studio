from __future__ import annotations

from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from server.sports_current_statcast import contextual_sources as sources
from server.sports_current_statcast.contextual_features import (
    GameInput,
    RIVALRY_AUTHORITY_STATUS,
    TeamAuthority,
    VenueAuthority,
    build_team_game_context,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STATIC_AUTHORITY_PATH = (
    REPOSITORY_ROOT
    / "server"
    / "sports_current_statcast"
    / "mlb_context_authorities_v1.json"
)
RIVALRY_PROPOSAL_PATH = (
    REPOSITORY_ROOT / "docs" / "MLB_RIVALRY_MAPPING_PROPOSAL_V1.json"
)


def _source_row(
    game_id: str,
    season: int,
    game_date: date,
    *,
    home_team: str = "A",
    away_team: str = "B",
    venue_source: str = "RETROSHEET",
    venue_source_id: str = "PARK-1",
    series_game_number: int | None = None,
    games_in_series: int | None = None,
    is_home_opener: bool = False,
    **extra: object,
) -> dict[str, object]:
    return {
        "canonicalGameId": game_id,
        "sourceGameId": f"source-{game_id}",
        "season": season,
        "gameDate": game_date,
        "homeTeam": home_team,
        "awayTeam": away_team,
        "venueSource": venue_source,
        "venueSourceId": venue_source_id,
        "scheduledStartUtc": None,
        "startTimeLocal": None,
        "seriesGameNumber": series_game_number,
        "gamesInSeries": games_in_series,
        "doubleheaderGameNumber": None,
        "isHomeOpener": is_home_opener,
        "durationMinutes": 180,
        "inningsPlayed": 9,
        "sourcePartitionId": f"partition-{game_id}",
        "sourceSha256": "a" * 64,
        "sourceCutoff": f"{game_date.isoformat()}T23:59:59Z",
        **extra,
    }


def _stub_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    legacy: list[dict[str, object]],
    current: list[dict[str, object]],
) -> None:
    monkeypatch.setattr(
        sources,
        "_legacy_games",
        lambda **_kwargs: (legacy, {"authority": "legacy"}),
    )
    monkeypatch.setattr(
        sources,
        "_current_games",
        lambda **_kwargs: (current, {"authority": "current"}),
    )


def test_schedule_duplicate_policy_accepts_only_exact_or_linked_resume_identity() -> None:
    original = {
        "gamePk": 7,
        "gameGuid": "guid-7",
        "gameDate": "2026-05-19T23:40:00Z",
        "officialDate": "2026-05-19",
        "resumeDate": "2026-05-21T17:10:00Z",
        "venue": {"id": 1},
        "teams": {
            "home": {"team": {"id": 10}},
            "away": {"team": {"id": 20}},
        },
    }
    resumed = {
        **original,
        "gameDate": "2026-05-21T17:10:00Z",
        "resumedFrom": "2026-05-19T23:40:00Z",
        "resumeDate": None,
        "seriesGameNumber": 2,
    }
    assert sources._same_suspended_game(original, resumed)
    assert not sources._same_suspended_game(
        original, {**resumed, "venue": {"id": 2}}
    )
    assert not sources._same_suspended_game(
        original,
        {
            **resumed,
            "teams": {
                "home": {"team": {"id": 11}},
                "away": {"team": {"id": 20}},
            },
        },
    )
def test_bundle_preserves_exact_venue_source_namespace_and_drops_game_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = [
        _source_row(
            "g-2023",
            2023,
            date(2023, 4, 1),
            venue_source="RETROSHEET",
            venue_source_id="1",
            homeScore=8,
            awayScore=2,
            winner="A",
            outcome="HOME_WIN",
        ),
        _source_row("g-2024", 2024, date(2024, 4, 1), venue_source_id="PARK-24"),
    ]
    current = [
        _source_row(
            "g-2025",
            2025,
            date(2025, 4, 1),
            venue_source="MLB_STATS_API",
            venue_source_id="1",
            completedState="Final",
            homeScore=4,
            awayScore=3,
        ),
        _source_row(
            "g-2026",
            2026,
            date(2026, 4, 1),
            venue_source="MLB_STATS_API",
            venue_source_id="VENUE-26",
        ),
    ]
    _stub_sources(monkeypatch, legacy=legacy, current=current)

    bundle = sources.load_context_source_bundle()
    by_id = {game.canonical_game_id: game for game in bundle.games}

    # Identical provider-local IDs remain distinct because source namespace is
    # part of the governed venue identity.
    assert by_id["g-2023"].venue_key == "RETROSHEET:1"
    assert by_id["g-2025"].venue_key == "MLB_STATS_API:1"
    assert by_id["g-2023"].venue_key != by_id["g-2025"].venue_key

    # Duration and innings are intentionally retained as prior-game workload
    # evidence. Scores, winner, outcome, and provider completion state are not
    # part of the normalized source contract.
    result_fields = {
        "home_score",
        "away_score",
        "home_runs",
        "away_runs",
        "runs_scored",
        "runs_allowed",
        "winner",
        "outcome",
        "result",
        "completed_state",
    }
    for game in bundle.games:
        assert result_fields.isdisjoint(asdict(game))


def test_bundle_infers_schedule_only_series_and_home_opener_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = [
        _source_row("series-1", 2023, date(2023, 4, 1)),
        _source_row("series-2", 2023, date(2023, 4, 2)),
        # One off-day still belongs to the same home/away/venue series block.
        _source_row("series-3", 2023, date(2023, 4, 4)),
        _source_row("next-series", 2023, date(2023, 4, 7)),
        _source_row("g-2024", 2024, date(2024, 4, 1), venue_source_id="PARK-24"),
    ]
    current = [
        _source_row(
            "g-2025",
            2025,
            date(2025, 4, 1),
            venue_source="MLB_STATS_API",
            venue_source_id="VENUE-25",
        ),
        _source_row(
            "g-2026",
            2026,
            date(2026, 4, 1),
            venue_source="MLB_STATS_API",
            venue_source_id="VENUE-26",
        ),
    ]
    _stub_sources(monkeypatch, legacy=legacy, current=current)

    by_id = {
        game.canonical_game_id: game
        for game in sources.load_context_source_bundle().games
    }

    assert [by_id[f"series-{number}"].series_game_number for number in (1, 2, 3)] == [1, 2, 3]
    assert [by_id[f"series-{number}"].games_in_series for number in (1, 2, 3)] == [3, 3, 3]
    assert by_id["next-series"].series_game_number == 1
    assert by_id["next-series"].games_in_series == 1
    assert by_id["series-1"].is_home_opener is True
    assert by_id["series-2"].is_home_opener is False
    assert by_id["next-series"].is_home_opener is False


def test_retrosheet_event_archive_content_sha_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePartition:
        year = 2023
        relative_path = "retrosheet/events/2023eve.zip"
        partition_id = "retrosheet/events/2023eve"
        file_sha256 = "0" * 64

        @staticmethod
        def absolute_path(_root: Path) -> Path:
            # Any existing regular file is sufficient: the source layer must
            # reject its bytes against the governed hash before attempting to
            # interpret the file as an archive.
            return STATIC_AUTHORITY_PATH

    monkeypatch.setattr(
        sources.bronze,
        "partitions",
        lambda _manifest, *, source: [FakePartition()],
    )

    with pytest.raises(sources.ContextSourceError, match="event archive SHA differs"):
        sources._event_headers({}, REPOSITORY_ROOT, (2023,))


def test_team_history_selection_excludes_same_date_and_future_workload() -> None:
    venue = VenueAuthority("venue", 40.0, -75.0, "America/New_York")
    teams = {
        "A": TeamAuthority("A", "AL", "E", "America/New_York"),
        "B": TeamAuthority("B", "AL", "E", "America/New_York"),
    }
    target = GameInput("target", date(2026, 8, 10), "A", "B", "venue")
    history = [
        GameInput(
            "prior",
            date(2026, 8, 9),
            "A",
            "B",
            "venue",
            duration_minutes=171,
            innings_played=9,
        ),
        GameInput(
            "same-day",
            date(2026, 8, 10),
            "A",
            "B",
            "venue",
            duration_minutes=999,
            innings_played=20,
        ),
        GameInput(
            "future",
            date(2026, 8, 11),
            "A",
            "B",
            "venue",
            duration_minutes=888,
            innings_played=19,
        ),
    ]

    row = build_team_game_context(
        target,
        "A",
        history=history,
        venues={"venue": venue},
        teams=teams,
    )

    assert row["history_cutoff_rule"] == "source.game_date < target.game_date"
    assert row["prior_game_id"] == "prior"
    assert row["previous_game_duration_minutes"] == 171
    assert row["previous_game_innings"] == 9
    assert row["games_last_3_days"] == 1


def test_static_context_authority_has_unique_valid_team_and_venue_aliases() -> None:
    authority = json.loads(STATIC_AUTHORITY_PATH.read_text(encoding="utf-8"))

    assert authority["authorityContract"] == "MLB_CONTEXT_STATIC_AUTHORITY_V1"
    assert authority["authorityVersion"] == 1
    assert len(authority["teams"]) == 30
    assert len(set(authority["teams"])) == 30
    for team_id, team in authority["teams"].items():
        assert team_id.strip() == team_id and team_id
        assert team["league"] in {"AL", "NL"}
        assert team["division"] in {"EAST", "CENTRAL", "WEST"}
        ZoneInfo(team["homeTimeZone"])

    venues = authority["venues"]
    venue_keys = [venue["venueKey"] for venue in venues]
    assert len(venue_keys) == len(set(venue_keys))

    for namespace in ("retrosheetParkIds", "mlbVenueIds"):
        aliases = [alias for venue in venues for alias in venue[namespace]]
        assert all(isinstance(alias, str) and alias.strip() == alias and alias for alias in aliases)
        assert len(aliases) == len(set(aliases))

    for venue in venues:
        assert -90.0 <= float(venue["latitude"]) <= 90.0
        assert -180.0 <= float(venue["longitude"]) <= 180.0
        ZoneInfo(venue["timeZone"])
        assert venue["altitudeFeet"] is None


def test_rivalry_mapping_remains_an_inactive_proposal() -> None:
    proposal = json.loads(RIVALRY_PROPOSAL_PATH.read_text(encoding="utf-8"))
    authority = json.loads(STATIC_AUTHORITY_PATH.read_text(encoding="utf-8"))

    assert proposal["mappingContract"] == "MLB_RIVALRY_MAPPING_V1"
    assert proposal["status"] == "PROPOSED_NOT_APPROVED"
    assert proposal["active"] is False
    assert RIVALRY_AUTHORITY_STATUS == "PROPOSED_NOT_APPROVED"

    teams = set(authority["teams"])
    pairs = [tuple(pair) for pair in proposal["proposedPairs"]]
    assert len(pairs) == len(set(map(frozenset, pairs)))
    assert all(len(pair) == 2 and pair[0] != pair[1] for pair in pairs)
    assert all(set(pair) <= teams for pair in pairs)
