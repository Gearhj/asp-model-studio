"""Synthetic identity/gate checks; not real-game training or performance."""
import csv
import io

import pytest

from server.sports_nba_gen1.recent_source import RecentSourceError, normalize_recent_source, source_game_key


FIELDS = ["date", "season", "neutral", "playoff", "team1", "team2", "is_home", "score1", "score2", "elo1_post"]


def pair(day="2024-01-01", season="2024", *, neutral="0", home="BOS", away="NYK", hs="110", aws="100", playoff=""):
    return [dict(zip(FIELDS, [day, season, neutral, playoff, home, away, "0" if neutral == "1" else "1", hs, aws, "UNUSED"])),
            dict(zip(FIELDS, [day, season, neutral, playoff, away, home, "0", aws, hs, "UNUSED"]))]


def payload(rows):
    target = io.StringIO(newline="")
    writer = csv.DictWriter(target, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return target.getvalue().encode()


def declare(rows, *, cups=None):
    keys = {source_game_key(int(row["season"]), row["date"], row["team1"], row["team2"]) for row in rows}
    context_keys = {source_game_key(item["seasonEnd"], item["date"], *item["teams"]) for item in (cups or [])}
    return {"regularSeasonEndDates": {"2024": "2024-04-14"}, "cupFinals": cups or [],
            "admittedSourceKeysBySeason": {"2024": sorted(keys - context_keys)},
            "contextOnlySourceKeysBySeason": {"2024": sorted(context_keys)}}


def test_normal_home_orientation_mirrors_counts_and_ignored_elo():
    source = pair(home="NYK", away="BOS")
    raw = payload(source)
    games, receipt = normalize_recent_source(raw, [2024], declare(source))
    game = games.iloc[0]
    assert game.home_team_code == "NYK" and game.away_team_code == "BOS"
    assert game.home_score == 110 and game.away_score == 100
    assert game.game_id == "nba-neil:2024:2024-01-01:BOS:NYK"
    assert game.source_game_id == game.game_id and game.source_row_numbers == "3,2"
    assert game.target_eligible and not game.neutral_site
    assert receipt["admittedSourceRows"] == 2 and receipt["sourcePhysicalBytes"] == len(raw)
    assert "elo1_post" not in games


def test_outside_roles_and_non_regular_scores_never_interpreted():
    admitted = pair()
    excluded = pair(season="2023", day="2023-01-01", hs="SEALED", aws="SEALED")
    excluded += pair(day="2024-04-15", hs="POSTSEASON", aws="POSTSEASON")
    excluded += pair(day="2024-03-01", playoff="p", hs="PROTECTED", aws="PROTECTED")
    _, receipt = normalize_recent_source(payload(admitted + excluded), [2024], declare(admitted))
    assert receipt["metadataExcludedRows"] == {"AFTER_DECLARED_REGULAR_SEASON_END": 2,
                                               "NON_REGULAR_PLAYOFF_FLAG": 2, "OUTSIDE_ALLOWED_SEASONS": 2}


def test_declared_key_gate_precedes_outcome_interpretation():
    admitted, unexpected = pair(), pair(day="2024-01-02", hs="DO_NOT_INTERPRET", aws="DO_NOT_INTERPRET")
    with pytest.raises(RecentSourceError, match="absent from frozen declaration"):
        normalize_recent_source(payload(admitted + unexpected), [2024], declare(admitted))


def test_cup_date_context_excludes_outcomes_and_model_rows():
    source = pair() + pair(day="2023-12-09", neutral="1", home="LAL", away="IND", hs="NOT_READ", aws="NOT_READ")
    scope = declare(source, cups=[{"seasonEnd": 2024, "date": "2023-12-09", "teams": ["IND", "LAL"]}])
    games, receipt = normalize_recent_source(payload(source), [2024], scope)
    assert len(games) == 1 and games.iloc[0].competition == "NBA_REGULAR_SEASON"
    context = receipt["contextOnlyEvents"][0]
    assert context["team_ids"] == ["nba-neil:franchise:IND", "nba-neil:franchise:LAL"]
    assert context["classification"] == "NBA_CUP_FINAL_DATE_ONLY"
    assert "home_score" not in context and receipt["contextOnlySourceRows"] == 2


@pytest.mark.parametrize("edit, message", [
    (lambda rows: rows.pop(), "exactly two"),
    (lambda rows: rows.append(rows[0].copy()), "exactly two"),
    (lambda rows: rows[1].update(score1="99"), "mirrored scores"),
    (lambda rows: rows[1].update(is_home="1"), "explicit home"),
    (lambda rows: rows[0].update(score1="110.5"), "integer count"),
    (lambda rows: rows[0].update(score1="100"), "cannot tie"),
])
def test_admitted_conflicts_fail_without_repair(edit, message):
    source = pair()
    scope = declare(source)
    edit(source)
    with pytest.raises(RecentSourceError, match=message):
        normalize_recent_source(payload(source), [2024], scope)


def test_missing_declared_game_and_neutral_home_flag_fail():
    source = pair()
    scope = declare(source + pair(day="2024-01-02"))
    with pytest.raises(RecentSourceError, match="missing="):
        normalize_recent_source(payload(source), [2024], scope)
    source = pair(neutral="1")
    source[0]["is_home"] = "1"
    with pytest.raises(RecentSourceError, match="is_home=0"):
        normalize_recent_source(payload(source), [2024], declare(source))
