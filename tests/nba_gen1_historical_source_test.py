"""Synthetic parsing/identity checks; never real NBA performance evidence."""
import csv
from copy import deepcopy
import io

import pytest

from server.sports_nba_gen1.historical_source import HistoricalSourceError, normalize_source


def pair(gid="g1", *, year=2014, neutral=False):
    common = dict(game_id=gid, lg_id="NBA", year_id=str(year), date_game=f"10/30/{year-1}", is_playoffs="0",
                  elo_i="NOT READ", elo_n="NOT READ", forecast="NOT READ")
    return [dict(common, _iscopy="0", team_id="AAA", fran_id="Alpha", opp_id="BBB", opp_fran="Beta",
                 pts="110", opp_pts="100", game_result="W", game_location="N" if neutral else "A"),
            dict(common, _iscopy="1", team_id="BBB", fran_id="Beta", opp_id="AAA", opp_fran="Alpha",
                 pts="100", opp_pts="110", game_result="L", game_location="N" if neutral else "H")]


def encoded(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def test_source_pair_is_oriented_by_home_not_copy_or_score_and_bytes_are_bound():
    raw = encoded(pair())
    rows, audit = normalize_source(raw, [2014])
    game = rows.iloc[0]
    assert game.game_id == "fte:g1" and game.source_game_id == "g1"
    assert game.home_team_id == "fte:franchise:Beta"
    assert game.home_score == 100 and game.away_score == 110
    assert game.game_date == "2013-10-30"
    assert not game.neutral_site and game.target_eligible
    assert audit["admittedGames"] == 1 and audit["admittedSourceRows"] == 2
    assert audit["sourcePhysicalBytes"] == len(raw)
    assert audit["aliasToFranchiseBySeason"]["2014"]["AAA"] == "fte:franchise:Alpha"
    assert "elo_i" not in rows and "forecast" not in rows


def test_metadata_gates_precede_outcome_interpretation():
    excluded_season = pair("old", year=2010)
    playoffs = pair("playoff")
    other_league = pair("other")
    for row in excluded_season + playoffs + other_league:
        row.update(pts="SEALED DO NOT CONVERT", opp_pts="SEALED DO NOT CONVERT", game_result="SEALED")
    for row in playoffs:
        row["is_playoffs"] = "1"
    for row in other_league:
        row["lg_id"] = "ABA"
    rows, audit = normalize_source(encoded(pair() + excluded_season + playoffs + other_league), [2014])
    assert rows.game_id.tolist() == ["fte:g1"]
    assert audit["metadataExcludedRows"] == {"NON_NBA": 2, "OUTSIDE_ALLOWED_SEASONS": 2, "PLAYOFFS": 2}


def test_neutral_pair_retains_explicit_publisher_axis_for_history_only():
    rows, audit = normalize_source(encoded(pair(neutral=True)), [2014])
    game = rows.iloc[0]
    assert game.neutral_site and not game.target_eligible
    assert game.orientation == "PUBLISHER_FOCAL_AXIS_NO_HOME_CLAIM"
    assert game.home_team_code == "AAA" and game.home_score == 110
    assert audit["neutralHistoryOnlyGameIds"] == ["fte:g1"]


@pytest.mark.parametrize("mutation, match", [
    (lambda rows: rows.pop(), "exactly two rows"),
    (lambda rows: rows[1].update(_iscopy="0"), "exactly two rows"),
    (lambda rows: rows[1].update(opp_id="CCC"), "identities differ"),
    (lambda rows: rows[1].update(pts="99"), "mirrored scores differ"),
    (lambda rows: rows[1].update(game_location="N"), "mirrored H/A or N/N"),
    (lambda rows: rows[1].update(game_result="W"), "W/L outcome disagrees"),
    (lambda rows: rows[0].update(pts="100"), "cannot tie"),
    (lambda rows: rows[0].update(date_game="2013-10-30T12:00:00Z"), "calendar date"),
])
def test_broken_identity_or_outcome_fails_instead_of_silent_repair(mutation, match):
    source = pair()
    mutation(source)
    with pytest.raises(HistoricalSourceError, match=match):
        normalize_source(encoded(source), [2014])


def test_conflicting_same_season_alias_and_duplicate_game_are_rejected():
    first = pair()
    second = deepcopy(pair("g2"))
    second[0]["fran_id"] = "Different"
    second[1]["opp_fran"] = "Different"
    with pytest.raises(HistoricalSourceError, match="multiple franchises"):
        normalize_source(encoded(first + second), [2014])
    with pytest.raises(HistoricalSourceError, match="exactly two rows"):
        normalize_source(encoded(first + first), [2014])
