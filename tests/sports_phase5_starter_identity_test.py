"""Focused tests for Phase 5F starter-identity projection + Q0/Q1 ablation.

Hermetic: temporal-safe candidate pool, target label never a feature, feature construction,
candidate scoring/normalization, top-k metrics, baselines, model round-trip, doubleheader
handling, and the Q1 starter-identity override (projected identity + duration, no silent actual-
starter fallback). Runtime-dependent record/registry checks skip when the artifact is absent.
No component retrained in tests; no betting metrics.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from server.sports_phase5 import starter_identity as si
from server.sports_phase5.participation_projection import TeamProjection

REPO = Path(__file__).resolve().parents[1]
from server.sports_cockpit.engine import RUNTIME_ROOT  # seam-aware runtime root
REC = RUNTIME_ROOT / "sports-phase5/starter-identity/latest.starter.json"

_spec = importlib.util.spec_from_file_location("p5f_cli", REPO / "scripts" / "run_mlb_starter_identity.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def _rotation_starter_rows(team="T", pitchers=("p0", "p1", "p2", "p3", "p4"), n_games=40, start="2024-04-01"):
    """A clean 5-man rotation: pitcher i starts game i (mod 5)."""
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    rows = []
    for i in range(n_games):
        rows.append({"game_id": f"g{i}", "team_id": team, "game_date": (d0 + dt.timedelta(days=i)).isoformat(),
                     "season": 2024, "starter_id": pitchers[i % len(pitchers)]})
    return rows


def test_candidate_pool_and_features_are_prior_date_only():
    rows = _rotation_starter_rows()
    apps = [{"team_id": r["team_id"], "game_date": r["game_date"], "pitcher_id": r["starter_id"]} for r in rows]
    games = si.build_starter_games(rows, apps)
    # a mid-season game: candidates must be prior starters only, and the label is the actual starter
    g = [x for x in games if x.game_id == "g20"][0]
    assert g.actual_starter == "p0"  # 20 % 5 == 0
    assert set(g.candidates).issubset({"p0", "p1", "p2", "p3", "p4"})
    assert g.label_index >= 0 and g.candidates[g.label_index] == "p0"
    # rotation_turn_proximity for the true starter (5 team-games since last start) should be near 0 (best)
    rot_idx = si.FEATURE_NAMES.index("rotation_turn_proximity")
    assert g.features[g.label_index, rot_idx] == 0.0  # tgss == 5 -> -|5-5| == 0


def test_label_not_leaked_first_game_pool_miss():
    rows = _rotation_starter_rows()
    apps = [{"team_id": r["team_id"], "game_date": r["game_date"], "pitcher_id": r["starter_id"]} for r in rows]
    games = si.build_starter_games(rows, apps)
    # the very first game has no prior starters -> no candidates -> excluded from games
    assert all(g.game_id != "g0" for g in games)
    # early games have partial pools; a pool miss is label_index == -1 (never silently corrected)
    early = [g for g in games if g.game_id in ("g1", "g2", "g3", "g4")]
    assert any(g.label_index == -1 for g in early)


def test_model_beats_baseline_on_clean_rotation():
    rows = _rotation_starter_rows(n_games=60)
    apps = [{"team_id": r["team_id"], "game_date": r["game_date"], "pitcher_id": r["starter_id"]} for r in rows]
    games = si.build_starter_games(rows, apps)
    covered = [g for g in games if g.label_index >= 0]
    model = si.StarterIdentityModel.fit(covered)
    m = si.rank_metrics(covered, model.probabilities)
    # a clean deterministic rotation should be almost perfectly recovered
    assert m["top1Accuracy"] > 0.9
    # probabilities normalize
    probs = model.probabilities(covered[10])
    assert abs(float(probs.sum()) - 1.0) < 1e-9 and np.all(probs >= 0)


def test_rank_metrics_and_baselines():
    rows = _rotation_starter_rows(n_games=40)
    apps = [{"team_id": r["team_id"], "game_date": r["game_date"], "pitcher_id": r["starter_id"]} for r in rows]
    games = [g for g in si.build_starter_games(rows, apps) if g.label_index >= 0]
    m = si.rank_metrics(games, lambda g: cli._softmax(si.baseline_scores(g, "S1_ROTATION_ORDER")))
    assert 0.0 <= m["top1Accuracy"] <= 1.0 and m["top2Accuracy"] >= m["top1Accuracy"]
    assert m["mrr"] > 0.0


def test_model_roundtrip():
    rows = _rotation_starter_rows(n_games=60)
    apps = [{"team_id": r["team_id"], "game_date": r["game_date"], "pitcher_id": r["starter_id"]} for r in rows]
    games = [g for g in si.build_starter_games(rows, apps) if g.label_index >= 0]
    model = si.StarterIdentityModel.fit(games)
    d = model.to_dict()
    model2 = si.StarterIdentityModel.from_dict(d)
    assert np.allclose(model.probabilities(games[5]), model2.probabilities(games[5]))
    assert d["featureNames"] == list(si.FEATURE_NAMES)


def test_doubleheader_two_starters_same_date():
    # two games same date -> two starters; both must be handled without inventing order
    rows = _rotation_starter_rows(n_games=30)
    # inject a same-date second game for the team
    rows.append({"game_id": "gDH", "team_id": "T", "game_date": rows[10]["game_date"], "season": 2024, "starter_id": "p2"})
    apps = [{"team_id": r["team_id"], "game_date": r["game_date"], "pitcher_id": r["starter_id"]} for r in rows]
    games = si.build_starter_games(rows, apps)
    dh = [g for g in games if g.game_id == "gDH"]
    assert len(dh) == 1 and dh[0].actual_starter == "p2"


# --- Q1 starter-identity override ---
def _tp(starter="actual", s2=19.0):
    return TeamProjection(lineup=tuple(f"b{i}" for i in range(9)), starter_uuid=starter, s2_bfp=s2,
                          reliever_uuids=("r0", "r1"), reliever_bfp=(5.0, 5.0), lineup_recall=0.8)


def test_q1_override_uses_projected_identity_and_duration():
    tp = _tp(starter="actual_uuid", s2=19.0)
    # correct projection -> use actual S2 duration, wrong count 0
    ps_correct = {"canonical": "actual_uuid", "correct": True, "duration": None, "topProb": 0.8, "gap": 0.4, "entropy": 0.5}
    new_tp, wrong = cli._override_starter(tp, ps_correct)
    assert new_tp.starter_uuid == "actual_uuid" and new_tp.s2_bfp == 19.0 and wrong == 0
    # wrong projection -> projected identity + proxy duration, wrong count 1, NO actual fallback
    ps_wrong = {"canonical": "other_uuid", "correct": False, "duration": 21.5, "topProb": 0.5, "gap": 0.05, "entropy": 1.2}
    new_tp2, wrong2 = cli._override_starter(tp, ps_wrong)
    assert new_tp2.starter_uuid == "other_uuid" and new_tp2.s2_bfp == 21.5 and wrong2 == 1
    assert new_tp2.starter_uuid != tp.starter_uuid  # did not silently keep the actual starter


def test_q1_override_missing_canonical_keeps_but_flagged():
    tp = _tp(starter="actual_uuid")
    new_tp, wrong = cli._override_starter(tp, {"canonical": None, "correct": False, "duration": 19.0})
    assert new_tp is tp and wrong == 0  # unresolved projection -> counted as absence, not a wrong swap


def test_magnitude_classifier():
    assert cli.p5e._magnitude(0.5) == "NEGLIGIBLE"
    assert cli.p5e._magnitude(2.0) == "SMALL"
    assert cli.p5e._magnitude(5.0) == "MEANINGFUL"


# --- runtime-dependent ---
@pytest.mark.skipif(not REC.is_file(), reason="starter-identity record not present")
def test_record_shape_and_no_betting():
    payload = json.loads(REC.read_text(encoding="utf-8"))["starterIdentity"]
    assert payload["modelDecision"].startswith("STARTER_IDENTITY_RESEARCH")
    assert set(payload["bySeason"]["2024"]) >= {"Q0", "Q1", "delta"}
    text = json.dumps({k: v for k, v in payload.items() if k not in ("limitations", "durationPolicy")}).lower()
    for banned in ("moneyline", "run_line", "runline", "closing odds", "clv", "sportsbook", "roi", "parlay", "wager"):
        assert banned not in text


@pytest.mark.skipif(not REC.is_file(), reason="starter-identity record not present")
def test_registry_projection_authority_gated():
    from server.sports_datasets.registry import _load_active_starter_identity
    payload = json.loads(REC.read_text(encoding="utf-8"))["starterIdentity"]
    auth = payload["datasetAuthority"]
    good = _load_active_starter_identity({"registration_id": auth["registrationId"], "manifest_sha": auth["manifestSha"]})
    assert good is not None and good["simulatorDecision"] == payload["simulatorDecision"]
    assert _load_active_starter_identity({"registration_id": "x", "manifest_sha": "y"}) is None
