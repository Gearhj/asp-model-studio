"""Focused tests for the Phase 5E projected-participation ablation (P0->P3).

Hermetic: branch definitions, no hidden oracle lineup in P1/P2/P3, starter-identity oracle in
P2/P3, no actual-bullpen leakage in P3, temporal B-state fallback accounting, projection
selection, and the magnitude classifier. Runtime-dependent record/registry checks skip when the
governed artifact is absent. No component is retrained in tests; no betting metrics.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from server.sports_phase5.participation_projection import (
    BRANCHES, TeamProjection, TemporalStateResolver, build_team_projections, build_branch_pa_uuids,
)
from server.sports_phase4.dynamic_contract import STATE_VALUE_COLUMNS

REPO = Path(__file__).resolve().parents[1]
from server.sports_cockpit.engine import RUNTIME_ROOT  # seam-aware runtime root
REC = RUNTIME_ROOT / "sports-phase5/projected-participation-ablation/latest.ablation.json"

_spec = importlib.util.spec_from_file_location("p5e_cli", REPO / "scripts" / "run_mlb_projected_participation_ablation.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


# --- actual vs projected sequences ---
def _actual(prefix_b, prefix_p, n):
    return [(f"{prefix_b}{i%9}", f"{prefix_p}_starter" if i < 20 else f"{prefix_p}_rel{(i-20)//5}") for i in range(n)]


def _proj(lineup_prefix, starter, s2, relievers):
    return TeamProjection(
        lineup=tuple(f"{lineup_prefix}{i}" for i in range(9)), starter_uuid=starter, s2_bfp=s2,
        reliever_uuids=tuple(relievers), reliever_bfp=tuple([5.0] * len(relievers)), lineup_recall=0.8)


def test_all_four_branches_defined():
    assert BRANCHES == ("P0", "P1", "P2", "P3")


def test_p0_uses_actual_sequences():
    away = _actual("ab", "ap", 38)
    home = _actual("hb", "hp", 36)
    seqs = build_branch_pa_uuids("P0", away_actual=away, home_actual=home,
                                 away_proj=_proj("AX", "as", 18, ["ar0"]), home_proj=_proj("HX", "hs", 18, ["hr0"]))
    assert seqs["away_pa"] == away and seqs["home_pa"] == home


def test_p1_projects_lineup_keeps_oracle_pitching():
    away = _actual("ab", "ap", 38)
    home = _actual("hb", "hp", 36)
    ap = _proj("AX", "as", 18, ["ar0"])
    hp = _proj("HX", "hs", 18, ["hr0"])
    seqs = build_branch_pa_uuids("P1", away_actual=away, home_actual=home, away_proj=ap, home_proj=hp)
    # batters are the projected lineup rotation (not the actual "ab*")
    assert seqs["away_pa"][0][0] == "AX0" and seqs["away_pa"][9][0] == "AX0"
    assert all(not b.startswith("ab") for b, _ in seqs["away_pa"])
    # pitching is oracle (actual pitcher sequence preserved)
    assert [p for _, p in seqs["away_pa"]] == [p for _, p in away]


def test_p2_projects_starter_duration_keeps_starter_identity():
    away = _actual("ab", "ap", 38)  # actual home-team starter faces first 20 (index<20)
    home = _actual("hb", "hp", 36)
    ap = _proj("AX", "as", 18, ["ar0", "ar1"])
    hp = _proj("HX", "hs_actual_starter", 10, ["hr0", "hr1"])  # projected removal at 10
    seqs = build_branch_pa_uuids("P2", away_actual=away, home_actual=home, away_proj=ap, home_proj=hp)
    away_pitchers = [p for _, p in seqs["away_pa"]]
    # starter identity retained: home_proj.starter_uuid for first round(10) batters
    assert away_pitchers[0] == "hs_actual_starter"
    assert away_pitchers[9] == "hs_actual_starter"
    # after the projected removal (10), the ACTUAL relievers (oracle bullpen) appear, not projected
    assert "ap_rel0" in away_pitchers  # actual reliever from `away` actual pitching tail
    assert "hr0" not in away_pitchers  # projected reliever must NOT appear in P2


def test_p3_projects_bullpen_no_actual_reliever_leakage():
    away = _actual("ab", "ap", 38)
    home = _actual("hb", "hp", 36)
    ap = _proj("AX", "as", 18, ["ar0", "ar1"])
    hp = _proj("HX", "hs_actual_starter", 10, ["hr0", "hr1"])
    seqs = build_branch_pa_uuids("P3", away_actual=away, home_actual=home, away_proj=ap, home_proj=hp)
    away_pitchers = [p for _, p in seqs["away_pa"]]
    assert away_pitchers[0] == "hs_actual_starter"  # starter identity oracle
    assert "hr0" in away_pitchers  # projected reliever appears
    assert "ap_rel0" not in away_pitchers  # actual reliever must NOT leak into P3


# --- temporal resolver ---
def _state_rows():
    rows = []
    for date in ("2024-04-01", "2024-05-01", "2024-06-01"):
        rows.append({"state_kind": "B_CUMULATIVE", "role": "BATTER", "canonical_player_uuid": "p1",
                     "game_date": date, **{n: float(i) for i, n in enumerate(STATE_VALUE_COLUMNS)}})
    return rows


def test_temporal_resolver_exact_prior_league():
    r = TemporalStateResolver(_state_rows(), state_table_sha="x")
    # exact date
    r.resolve("p1", "BATTER", "2024-05-01"); assert r.exact == 1
    # prior date (between materialized dates) -> most recent prior
    v = r.resolve("p1", "BATTER", "2024-05-15"); assert r.stale == 1
    assert v[0] == 0.0  # values from 2024-05-01 row (log_odds_strikeout index 0 -> 0.0)
    # before any date -> league fallback
    r.resolve("p1", "BATTER", "2024-03-01"); assert r.league == 1
    # unknown player -> league fallback
    r.resolve("pX", "BATTER", "2024-05-01"); assert r.league == 2
    fb = r.fallback_summary()
    assert fb["resolvedExact"] == 1 and fb["resolvedPriorState"] == 1 and fb["roleLeagueFallback"] == 2


def test_build_team_projections_top9_and_recall():
    lineup_rows = [{"canonical_player_uuid": f"p{i}", "l1_probability": 0.9 - i * 0.05,
                    "target_start": 1 if i < 9 else 0} for i in range(15)]
    starter_rows = [{"canonical_player_uuid": "sp", "s2_bfp": 19.0}]
    bullpen_rows = [{"canonical_player_uuid": f"r{i}", "b1_probability": 0.5 - i * 0.05, "b1_bfp": 4.0} for i in range(5)]
    tp = build_team_projections(lineup_rows, starter_rows, bullpen_rows)
    assert len(tp.lineup) == 9 and tp.lineup[0] == "p0"
    assert tp.starter_uuid == "sp" and abs(tp.s2_bfp - 19.0) < 1e-9
    assert tp.reliever_uuids[0] == "r0"
    assert tp.lineup_recall == 1.0  # top-9 exactly the 9 actual starters


def test_magnitude_thresholds():
    assert cli._magnitude(0.5) == "NEGLIGIBLE"
    assert cli._magnitude(2.0) == "SMALL"
    assert cli._magnitude(5.0) == "MEANINGFUL"
    assert cli._magnitude(12.0) == "LARGE"
    assert cli._magnitude(None) == "UNKNOWN"


# --- runtime-dependent record / registry ---
@pytest.mark.skipif(not REC.is_file(), reason="ablation record not present")
def test_record_branches_and_no_betting():
    payload = json.loads(REC.read_text(encoding="utf-8"))["ablation"]
    assert set(payload["bySeason"]["2024"]["branches"]) == {"P0", "P1", "P2", "P3"}
    text = json.dumps({k: v for k, v in payload.items() if k not in ("limitations", "branchLabels")}).lower()
    for banned in ("moneyline", "run_line", "runline", "closing odds", "clv", "sportsbook", "roi", "parlay", "wager"):
        assert banned not in text


@pytest.mark.skipif(not REC.is_file(), reason="ablation record not present")
def test_registry_projection_authority_gated():
    from server.sports_datasets.registry import _load_active_participation_ablation
    payload = json.loads(REC.read_text(encoding="utf-8"))["ablation"]
    auth = payload["datasetAuthority"]
    good = _load_active_participation_ablation({"registration_id": auth["registrationId"], "manifest_sha": auth["manifestSha"]})
    assert good is not None and good["overallDecision"] == payload["overallDecision"]
    assert _load_active_participation_ablation({"registration_id": "x", "manifest_sha": "y"}) is None
