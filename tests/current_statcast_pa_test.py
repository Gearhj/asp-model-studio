from __future__ import annotations

import pyarrow as pa
import pytest

from server.sports_silver import current_statcast_pa as CURRENT
from server.sports_silver.canonical_ids import canonical_player_id


_RESOLVED = {
    "100": canonical_player_id("batter-person"),
    "200": canonical_player_id("pitcher-person"),
}

_LINEAGE = {
    "partition_id": "statcast:regular:2026-08-27",
    "partition_date": "2026-08-27",
    "source_cutoff": "2026-08-28T00:15:00Z",
    "source_partition_sha256": "a" * 64,
    "source_manifest_sha256": "b" * 64,
}


def _row(**changes):
    result = {
        "game_pk": 700001,
        "game_date": "2026-08-27",
        "game_year": 2026,
        "game_type": "R",
        "home_team": "NYY",
        "away_team": "BOS",
        "inning": 1,
        "inning_topbot": "Top",
        "outs_when_up": 1,
        "on_1b": 301,
        "on_2b": None,
        "on_3b": 303,
        "home_score": 2,
        "away_score": 1,
        "bat_score": 1,
        "fld_score": 2,
        "at_bat_number": 1,
        "pitch_number": 1,
        "batter": 100,
        "pitcher": 200,
        "stand": "L",
        "p_throws": "R",
        "pitch_type": "FF",
        "release_speed": 95.2,
        "bb_type": None,
        "events": None,
        "description": "ball",
        "des": "Ball",
    }
    result.update(changes)
    return result


def _normalize(rows, *, final_game_pks=(700001,), resolved_mlbam=_RESOLVED):
    return CURRENT.normalize_current_partition(
        pa.Table.from_pylist(rows),
        final_game_pks=final_game_pks,
        resolved_mlbam=resolved_mlbam,
        **_LINEAGE,
    )


def test_exact_reviewed_statcast_event_crosswalk():
    expected = {
        "strikeout": "STRIKEOUT",
        "walk": "WALK_HBP_CI",
        "home_run": "HOME_RUN",
        "single": "SINGLE",
        "double": "DOUBLE",
        "triple": "TRIPLE",
        "field_out": "BIP_OUT",
        "field_error": "OTHER_REACH",
    }
    assert CURRENT.PA_CLASS_ORDER == (
        "STRIKEOUT",
        "WALK_HBP_CI",
        "HOME_RUN",
        "SINGLE",
        "DOUBLE",
        "TRIPLE",
        "BIP_OUT",
        "OTHER_REACH",
    )
    assert {event: CURRENT.map_pa_event(event) for event in expected} == expected
    assert CURRENT.map_pa_event("  STRIKEOUT  ") == "STRIKEOUT"
    assert CURRENT.map_pa_event("truncated_pa") is None
    assert CURRENT.map_pa_event(None) is None


def test_one_pa_uses_minimum_pitch_context_and_maximum_pitch_event():
    # Deliberately place the terminal pitch first to prove source order is not authority.
    rows = [
        _row(
            pitch_number=2,
            events="field_out",
            description="hit_into_play",
            outs_when_up=2,
            on_1b=None,
            on_3b=None,
            bat_score=9,
            fld_score=9,
        ),
        _row(pitch_number=1, events=None, outs_when_up=1, bat_score=1, fld_score=2),
    ]
    result = _normalize(rows)

    assert len(result.fact_pa) == 1
    assert len(result.fact_pitch) == 2
    assert result.rejects == []
    plate_appearance = result.fact_pa[0]
    assert plate_appearance["outcome"] == "BIP_OUT"
    assert plate_appearance["paEvent"] == "field_out"
    assert plate_appearance["pitchCount"] == 2
    assert plate_appearance["firstPitchNumber"] == 1
    assert plate_appearance["lastPitchNumber"] == 2
    assert plate_appearance["terminalSourceRowIndex"] == 0
    assert plate_appearance["outsBeforePa"] == 1
    assert plate_appearance["onFirstMlbamIdBeforePa"] == "301"
    assert plate_appearance["onFirstOccupiedBeforePa"] is True
    assert plate_appearance["onSecondOccupiedBeforePa"] is False
    assert plate_appearance["onThirdMlbamIdBeforePa"] == "303"
    assert plate_appearance["batScoreBeforePa"] == 1
    assert plate_appearance["fieldScoreBeforePa"] == 2
    assert plate_appearance["stand"] == "L"
    assert plate_appearance["pThrows"] == "R"
    assert plate_appearance["sourcePartitionId"] == _LINEAGE["partition_id"]
    assert plate_appearance["sourcePartitionSha256"] == "a" * 64
    assert plate_appearance["sourceManifestSha256"] == "b" * 64
    assert plate_appearance["sourceCutoff"] == _LINEAGE["source_cutoff"]
    assert len(plate_appearance["finalGameAuthoritySha256"]) == 64
    assert plate_appearance["finalGameAuthoritySha256"] == result.counts["finalGameAuthoritySha256"]
    assert plate_appearance["rulesRegime"] == "MLB_2026_REGULAR_RULES"
    assert plate_appearance["is2026RulesRegime"] is True
    assert plate_appearance["normalizerContract"] == CURRENT.NORMALIZER_CONTRACT
    assert set(plate_appearance) == set(CURRENT.PA_FIELDS)
    assert all(set(row) == set(CURRENT.PITCH_FIELDS) for row in result.fact_pitch)
    assert result.counts["pitchRowsReconcile"] is True
    assert result.counts["paGroupsReconcile"] is True


def test_all_eight_outcomes_emit_in_frozen_order():
    representative_events = (
        "strikeout_double_play",
        "catcher_interf",
        "home_run",
        "single",
        "double",
        "triple",
        "grounded_into_double_play",
        "fielders_choice",
    )
    rows = [
        _row(at_bat_number=index, events=event)
        for index, event in enumerate(representative_events, start=1)
    ]
    result = _normalize(rows)

    assert [row["outcome"] for row in result.fact_pa] == list(CURRENT.PA_CLASS_ORDER)
    assert result.counts["classCounts"] == {name: 1 for name in CURRENT.PA_CLASS_ORDER}
    assert result.counts["acceptedPlateAppearances"] == 8
    assert result.counts["rejectedPlateAppearances"] == 0


def test_missing_unknown_contradictory_and_duplicate_events_fail_closed():
    rows = [
        _row(at_bat_number=1, pitch_number=1, events=None),
        _row(at_bat_number=2, pitch_number=1, events="truncated_pa"),
        _row(at_bat_number=3, pitch_number=1, events="walk"),
        _row(at_bat_number=3, pitch_number=2, events="single"),
        _row(at_bat_number=4, pitch_number=1, events=None),
        _row(at_bat_number=4, pitch_number=1, events="field_out"),
    ]
    result = _normalize(rows)

    assert result.fact_pa == []
    assert result.fact_pitch == []
    reasons = [row["reason"] for row in result.rejects]
    assert reasons == [
        "MISSING_TERMINAL_EVENT",
        "UNKNOWN_TERMINAL_EVENT",
        "CONTRADICTORY_PA_EVENTS",
        "DUPLICATE_PITCH_NATURAL_KEY",
    ]
    unknown = result.rejects[1]
    assert unknown["rawEvent"] == "truncated_pa"
    assert unknown["mlbamGamePk"] == "700001"
    assert unknown["atBatNumber"] == "2"
    assert unknown["gameDate"] == "2026-08-27"
    assert result.counts["rejectedPitchRows"] == 6
    assert result.counts["pitchRowsReconcile"] is True
    assert result.counts["paGroupsReconcile"] is True


def test_nonfinal_and_unresolved_player_groups_emit_only_reject_evidence():
    rows = [
        _row(at_bat_number=1, pitcher=999, events="field_out"),
        _row(game_pk=700002, at_bat_number=2, events="single"),
        _row(at_bat_number=3, batter=None, events="walk"),
    ]
    result = _normalize(rows)

    assert result.fact_pa == []
    assert result.fact_pitch == []
    assert [row["reason"] for row in result.rejects] == [
        "UNRESOLVED_PLAYER_IDENTITY",
        "MISSING_PLAYER_IDENTITY",
        "GAME_NOT_FINAL",
    ]
    assert result.counts["reasonCounts"] == {
        "GAME_NOT_FINAL": 1,
        "MISSING_PLAYER_IDENTITY": 1,
        "UNRESOLVED_PLAYER_IDENTITY": 1,
    }
    assert result.counts["representedFinalGameCount"] == 0


def test_lineage_authority_and_partition_date_are_fail_closed():
    with pytest.raises(CURRENT.CurrentStatcastNormalizationError, match="complete source lineage"):
        CURRENT.normalize_current_partition(
            pa.Table.from_pylist([_row(events="single")]),
            final_game_pks=(700001,),
            resolved_mlbam=_RESOLVED,
            **(_LINEAGE | {"source_partition_sha256": ""}),
        )

    result = CURRENT.normalize_current_partition(
        pa.Table.from_pylist([_row(game_date="2026-08-26", events="single")]),
        final_game_pks=(700001,),
        resolved_mlbam=_RESOLVED,
        **_LINEAGE,
    )
    assert result.fact_pa == []
    assert result.rejects[0]["reason"] == "PARTITION_DATE_MISMATCH"
    assert set(result.rejects[0]) == set(CURRENT.REJECT_FIELDS)

    postseason = _normalize([_row(game_type="F", events="home_run")])
    assert postseason.fact_pa == []
    assert postseason.rejects[0]["reason"] == "NON_REGULAR_GAME"

    incomplete = pa.Table.from_pylist([_row(events="single")]).drop(["p_throws"])
    with pytest.raises(CURRENT.CurrentStatcastNormalizationError, match="p_throws"):
        CURRENT.normalize_current_partition(
            incomplete,
            final_game_pks=(700001,),
            resolved_mlbam=_RESOLVED,
            **_LINEAGE,
        )
