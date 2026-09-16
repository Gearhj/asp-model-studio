"""Phase 7D.5A.2 (Repair 1) — strict, typed point-in-time chronology, adversarially.

Every Codex chronology reproduction is a permanent case here. The reference counts strictly-earlier same-batter PAs
with an INDEPENDENT key (parsed date, numeric at-bat) — it does not import or copy production sorting/canonicalization.
"""
from __future__ import annotations

import datetime as dt

import pytest

from server.sports_modeling import silver_transform as ST
from server.sports_modeling.silver_transform import SilverTransformError


def _row(b, date, gid, ab, pid, season=2023, **extra):
    r = {"batter_canonical_player_uuid": b, "game_date": date, "game_id": gid, "at_bat_number": ab,
         "plate_appearance_id": pid, "season": season}
    r.update(extra)
    return r


def _ref_prior(rows):
    """INDEPENDENT reference: for each row, count same-batter rows strictly earlier by (parsed date, at_bat int)."""
    def key(r):
        return (dt.date.fromisoformat(r["game_date"]), int(r["at_bat_number"]), str(r["plate_appearance_id"]))
    out = []
    for r in rows:
        kr = key(r)
        out.append(float(sum(1 for o in rows
                             if o["batter_canonical_player_uuid"] == r["batter_canonical_player_uuid"] and key(o) < kr)))
    return out


# ---------------------------------------------------------------- numeric ordering: 2 before 10
def test_at_bat_2_sorts_before_10_numerically():
    rows = [_row("b1", "2023-04-01", "g1", 2, "pa2"), _row("b1", "2023-04-01", "g1", 10, "pa10")]
    res = ST.compute_prior_pa(rows)
    by_pid = {r["plate_appearance_id"]: f for r, f in zip(rows, res)}
    assert by_pid["pa2"]["prior_pa_count"] == 0.0     # at-bat 2 is EARLIER
    assert by_pid["pa10"]["prior_pa_count"] == 1.0     # at-bat 10 is LATER
    assert res == [{"prior_pa_count": p, "log1p_prior_pa_count": __import__("math").log1p(p)}
                   for p in _ref_prior(rows)]


def test_matches_independent_reference_on_a_longer_sequence():
    rows = [_row("b1", "2023-04-01", "g1", ab, f"pa{ab}") for ab in (1, 2, 3, 10, 11, 20)]
    got = [f["prior_pa_count"] for f in ST.compute_prior_pa(rows)]
    assert got == _ref_prior(rows) == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]


# ---------------------------------------------------------------- prohibited target on ANY row
def test_target_on_second_row_fails_closed():
    rows = [_row("b1", "2023-04-01", "g1", 1, "p1"), _row("b1", "2023-04-01", "g1", 2, "p2", outcome="HR")]
    with pytest.raises(SilverTransformError):
        ST.compute_prior_pa(rows)


@pytest.mark.parametrize("col", ["outcome", "label", "target", "launch_speed", "estimated_woba", "events"])
def test_any_prohibited_column_on_any_row_fails_closed(col):
    rows = [_row("b1", "2023-04-01", "g1", 1, "p1"), _row("b1", "2023-04-01", "g1", 2, "p2", **{col: 1})]
    with pytest.raises(SilverTransformError):
        ST.compute_prior_pa(rows)


# ---------------------------------------------------------------- missing / null / mistyped keys
@pytest.mark.parametrize("drop", ["game_date", "game_id", "at_bat_number", "plate_appearance_id",
                                  "batter_canonical_player_uuid"])
def test_missing_required_chronology_column_fails_closed(drop):
    r = _row("b1", "2023-04-01", "g1", 1, "p1")
    del r[drop]
    with pytest.raises(SilverTransformError):
        ST.compute_prior_pa([r])


@pytest.mark.parametrize("col", ["game_date", "game_id", "at_bat_number", "plate_appearance_id"])
def test_null_chronology_value_fails_closed(col):
    r = _row("b1", "2023-04-01", "g1", 1, "p1")
    r[col] = None
    with pytest.raises(SilverTransformError):
        ST.compute_prior_pa([r])


@pytest.mark.parametrize("bad", ["10", 10.0, True])
def test_string_or_nonint_at_bat_number_fails_closed(bad):
    with pytest.raises(SilverTransformError):
        ST.compute_prior_pa([_row("b1", "2023-04-01", "g1", bad, "p1")])


def test_unparseable_game_date_fails_closed():
    with pytest.raises(SilverTransformError):
        ST.compute_prior_pa([_row("b1", "not-a-date", "g1", 1, "p1")])


# ---------------------------------------------------------------- uniqueness / determinism
def test_duplicate_pa_id_across_different_batters_fails_closed():
    rows = [_row("b1", "2023-04-01", "g1", 1, "DUP"), _row("b2", "2023-04-01", "g1", 1, "DUP")]
    with pytest.raises(SilverTransformError):
        ST.compute_prior_pa(rows)


def test_duplicate_governed_key_same_batter_fails_closed():
    rows = [_row("b1", "2023-04-01", "g1", 1, "p1"), _row("b1", "2023-04-01", "g1", 1, "p2")]
    # identical (date, game, at_bat) for the same batter — only the id differs; ambiguous same-instant order
    # is allowed ONLY because the id tie-breaks; make the ids collide on everything but force a same-key check:
    rows2 = [_row("b1", "2023-04-01", "g1", 1, "same"), _row("b1", "2023-04-01", "g1", 1, "same")]
    with pytest.raises(SilverTransformError):
        ST.compute_prior_pa(rows2)


def test_same_day_multiple_games_without_sequence_fails_closed():
    rows = [_row("b1", "2023-04-01", "gA", 1, "p1"), _row("b1", "2023-04-01", "gB", 1, "p2")]
    with pytest.raises(SilverTransformError):
        ST.compute_prior_pa(rows)


def test_same_day_multiple_games_with_governed_sequence_is_ordered():
    rows = [_row("b1", "2023-04-01", "gB", 1, "p2", game_sequence=2),
            _row("b1", "2023-04-01", "gA", 1, "p1", game_sequence=1)]
    res = {r["plate_appearance_id"]: f["prior_pa_count"] for r, f in zip(rows, ST.compute_prior_pa(rows))}
    assert res["p1"] == 0.0 and res["p2"] == 1.0     # game_sequence orders same-day games, not lexical id


# ---------------------------------------------------------------- invariance
def _seq(n, batter="b1", start_ab=1):
    return [_row(batter, "2023-04-01", "g1", start_ab + i, f"{batter}-p{start_ab + i}") for i in range(n)]


def test_input_order_does_not_change_values():
    base = _seq(6)
    shuffled = [base[i] for i in (3, 0, 5, 1, 4, 2)]
    a = {r["plate_appearance_id"]: f for r, f in zip(base, ST.compute_prior_pa(base))}
    b = {r["plate_appearance_id"]: f for r, f in zip(shuffled, ST.compute_prior_pa(shuffled))}
    assert a == b


def test_appending_future_rows_does_not_change_earlier_values():
    base = _seq(4)
    extended = base + _seq(3, start_ab=100)
    a = {r["plate_appearance_id"]: f for r, f in zip(base, ST.compute_prior_pa(base))}
    b = {r["plate_appearance_id"]: f for r, f in zip(extended, ST.compute_prior_pa(extended))}
    for pid in a:
        assert a[pid] == b[pid]     # earlier rows unaffected by appended future PAs


def test_batter_histories_are_isolated():
    rows = _seq(3, "b1") + _seq(5, "b2")
    res = {r["plate_appearance_id"]: f["prior_pa_count"] for r, f in zip(rows, ST.compute_prior_pa(rows))}
    assert res["b1-p3"] == 2.0 and res["b2-p5"] == 4.0     # counts never cross batters


# ---------------------------------------------------------------- season authorization
def test_unauthorized_2019_season_fails_closed():
    with pytest.raises(SilverTransformError):
        ST.compute_prior_pa([_row("b1", "2019-04-01", "g1", 1, "p1", season=2019)], season_of_row=lambda r: r["season"])


@pytest.mark.parametrize("sealed", [2025, 2026])
def test_sealed_or_prospective_season_fails_closed(sealed):
    with pytest.raises(SilverTransformError):
        ST.compute_prior_pa([_row("b1", f"{sealed}-04-01", "g1", 1, "p1", season=sealed)],
                            season_of_row=lambda r: r["season"])


def test_authorized_2021_2024_seasons_pass():
    for s in (2021, 2022, 2023, 2024):
        ST.compute_prior_pa([_row("b1", f"{s}-04-01", "g1", 1, "p1", season=s)], season_of_row=lambda r: r["season"])
