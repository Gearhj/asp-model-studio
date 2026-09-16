from datetime import date, datetime, timezone

import pytest

from server.sports_current_statcast.contextual_features import (
    CONTEXT_FEATURES, GAME_CONTEXT_FEATURES, TEAM_CONTEXT_FEATURES,
    INTERACTION_FEATURES, MISSING_FLAG_FEATURES, FUTURE_ABLATION_FAMILIES,
    MLB_TEAM_AUTHORITIES,
    ORDERED_GOLD_PLUS_CONTEXT_FEATURES, RIVALRY_AUTHORITY_STATUS,
    GameInput, TeamAuthority, VenueAuthority, build_team_game_context,
    haversine_miles, venue_holidays,
)
from server.sports_gold.contracts import GOLD_FEATURES


NY = VenueAuthority("ny", 40.8296, -73.9262, "America/New_York")
LA = VenueAuthority("la", 34.0739, -118.2400, "America/Los_Angeles")
TOR = VenueAuthority("tor", 43.6414, -79.3894, "America/Toronto", country="CA", region="ON")
TEAMS = {
    "A": TeamAuthority("A", "AL", "E", "America/Los_Angeles"),
    "B": TeamAuthority("B", "AL", "E", "America/New_York"),
    "C": TeamAuthority("C", "NL", "W", "America/Los_Angeles"),
}


def game(gid, day, home="A", away="B", venue="ny", hour=23, **kwargs):
    return GameInput(gid, day, home, away, venue, datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc), **kwargs)


def test_order_is_gold_48_then_exact_context_families():
    assert ORDERED_GOLD_PLUS_CONTEXT_FEATURES[:48] == tuple(GOLD_FEATURES)
    assert ORDERED_GOLD_PLUS_CONTEXT_FEATURES[48:] == CONTEXT_FEATURES
    assert CONTEXT_FEATURES[:len(GAME_CONTEXT_FEATURES)] == GAME_CONTEXT_FEATURES
    assert f"batting_{TEAM_CONTEXT_FEATURES[0]}" in CONTEXT_FEATURES
    assert len(set(ORDERED_GOLD_PLUS_CONTEXT_FEATURES)) == len(ORDERED_GOLD_PLUS_CONTEXT_FEATURES)
    assert len(MLB_TEAM_AUTHORITIES) == 30 and {"ATH", "ATL", "AZ"} <= set(MLB_TEAM_AUTHORITIES)
    assert tuple(FUTURE_ABLATION_FAMILIES) == (
        "A CORE_GOLD_48", "B CORE_PLUS_CALENDAR", "C CORE_PLUS_REST_TRAVEL",
        "D CORE_PLUS_CIRCADIAN", "E CORE_PLUS_DIVISION_RIVALRY",
        "F CORE_PLUS_CALENDAR_TRAVEL", "G FULL_CONTEXTUAL_CHALLENGER",
    )
    assert all(values[:48] == tuple(GOLD_FEATURES) for values in FUTURE_ABLATION_FAMILIES.values())
    assert INTERACTION_FEATURES == (
        "home_x_friday_night", "home_x_weekend", "home_x_holiday", "home_x_rivalry",
        "eastward_travel_x_early_start", "long_travel_x_short_rest",
        "prior_extra_innings_x_travel", "doubleheader_x_short_rest",
        "road_trip_length_x_travel",
    )
    assert {"previous_game_end_time_missing", "travel_path_missing", "venue_coordinate_missing",
            "time_zone_missing", "holiday_calendar_missing"} <= set(MISSING_FLAG_FEATURES)


def test_haversine_and_calendar_holidays_are_deterministic():
    assert haversine_miles(NY, NY) == 0.0
    assert haversine_miles(NY, LA) == pytest.approx(2446, rel=.02)
    assert date(2026, 7, 3) in venue_holidays(2026, NY)  # July 4 Saturday observed Friday
    assert date(2026, 7, 1) in venue_holidays(2026, TOR)


def test_rest_density_trip_doubleheader_and_same_date_leakage():
    target = game("g4", date(2026, 7, 4), home="C", away="A", venue="la", series_game_number=2, doubleheader_game_number=2)
    history = [
        game("g1", date(2026, 7, 1), home="B", away="A"),
        game("g2", date(2026, 7, 3), home="B", away="A"),
        game("same-day", date(2026, 7, 4), home="B", away="A"),
    ]
    row = build_team_game_context(target, "A", history=history, venues={"ny": NY, "la": LA}, teams=TEAMS)
    assert row["prior_game_id"] == "g2" and row["days_since_previous_game"] == 1
    assert row["games_last_3_days"] == 2 and row["road_trip_game_number"] == 3
    assert row["is_doubleheader"] == 1 and row["doubleheader_game_number"] == 2
    assert row["repeat_opponent_within_7_days"] == 0


def test_next_day_prior_identity_uses_second_doubleheader_game():
    first = game(
        "z-game-one", date(2026, 7, 3), home="B", away="A",
        doubleheader_game_number=1, innings_played=11,
    )
    second = game(
        "a-game-two", date(2026, 7, 3), home="B", away="A",
        doubleheader_game_number=2, innings_played=9,
    )
    target = game("next-day", date(2026, 7, 4), home="B", away="A")

    row = build_team_game_context(
        target, "A", history=[first, second], venues={"ny": NY}, teams=TEAMS
    )

    assert row["prior_game_id"] == "a-game-two"
    assert row["previous_game_innings"] == 9
    assert row["previous_game_extra_innings"] == 0


def test_timezone_direction_dst_and_body_clock_are_transparent():
    prior = game("g1", date(2026, 7, 3), home="B", away="A", venue="la")
    target = game("g2", date(2026, 7, 4), home="B", away="A", venue="ny")
    row = build_team_game_context(target, "A", history=[prior], venues={"ny": NY, "la": LA}, teams=TEAMS)
    assert row["time_zone_change_hours"] == 3
    assert row["eastward_time_zone_change_hours"] == 3 and row["westward_time_zone_change_hours"] == 0
    assert row["start_hour_in_previous_venue_time_zone"] == 16
    assert row["local_start_hour"] == 19
    assert row["local_body_clock_offset_hours"] == 3
    assert row["circadian_disruption_score"] == pytest.approx(
        row["circadian_timezone_component"]
        + row["circadian_body_clock_component"]
        + row["circadian_early_east_component"]
        + row["circadian_late_west_component"]
        + row["circadian_morning_component"]
        + row["circadian_short_recovery_component"]
    )


def test_daylight_saving_change_at_same_venue_is_not_travel():
    prior_day = date(2026, 3, 7)
    target_day = date(2026, 3, 9)
    prior = GameInput(
        "g1", prior_day, "A", "B", "ny",
        datetime(2026, 3, 7, 18, tzinfo=timezone.utc),
    )
    target = GameInput(
        "g2", target_day, "A", "B", "ny",
        datetime(2026, 3, 9, 18, tzinfo=timezone.utc),
    )
    row = build_team_game_context(
        target, "A", history=[prior], venues={"ny": NY}, teams=TEAMS
    )
    assert row["time_zone_change_hours"] == 0
    assert row["crossed_time_zone"] == 0


def test_missing_authority_is_explicit_and_end_time_is_never_inferred():
    target = GameInput("g", date(2026, 4, 1), "A", "B", "unknown")
    row = build_team_game_context(target, "A", history=[], venues={}, teams=TEAMS)
    assert row["actual_end_utc"] is None
    assert row["travel_distance_miles"] is None
    assert row["previous_game_missing"] == 1 and row["current_start_missing"] == 1


def test_rivalry_is_governed_inactive_not_subjectively_inferred():
    row = build_team_game_context(game("g", date(2026, 6, 1)), "A", history=[], venues={"ny": NY}, teams=TEAMS)
    assert RIVALRY_AUTHORITY_STATUS == "PROPOSED_NOT_APPROVED"
    assert row["rivalry_authority_status"] == "PROPOSED_NOT_APPROVED"
    assert row["rivalry_mapping_missing"] == 1
    assert row["rivalry_game"] is None and row["home_x_rivalry"] is None
    assert "travel_x_recent_bullpen_workload" in row["excluded_interactions"]
    assert "month_x_temperature" in row["excluded_interactions"]
