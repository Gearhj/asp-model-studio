"""Focused evidence semantics; no model loading or provider calls."""
from scripts.build_mlb_v19_feature_quality import CATEGORIES, cell_quality, cold_start_spec


def minimal_field(name, family):
    return {"field": name, "sourceFamily": family, "order": 0, "definition": "test domain",
            "entityGrain": "PLAYER_ROLE", "frozenMissingTreatment": {}, "actualAbsentTreatment": "retained"}


def test_populated_gap_indicator_is_not_numeric_source_coverage():
    field = minimal_field("fielding_recent_bullpen_workload_missing", "TEAM_SCHEDULE_VENUE_CONTEXT")
    category, state, _ = cell_quality(field, {"value": 1, "supported": True}, {})
    assert category == CATEGORIES[4] and state == "SOURCE_FAILURE"


def test_annual_absence_is_distinct_from_short_current_window():
    annual = minimal_field("pitcher_prior_missing", "ANNUAL_PLAYER_PRIOR")
    recent = minimal_field("pitcher_last250_whiff_rate", "COMPLETED_PA_PITCH_HISTORY")
    assert cell_quality(annual, {"value": 1, "supported": True}, {})[0] == CATEGORIES[3]
    assert cell_quality(recent, {"value": 0.2, "supported": True}, {"pitcher_last250_bf_count": 46})[0] == CATEGORIES[1]
    specification = cold_start_spec(recent)
    assert specification["sourceFailureCanBecomeZero"] is False
    assert specification["genericMedianOrMode"] is False
    assert specification["intendedUncertaintyOnly"] is False
    assert len(specification["states"]) == 6
