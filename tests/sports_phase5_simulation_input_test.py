"""Focused tests for the Phase 5C simulation input layer (gates 5, 6, 7).

Hermetic where possible (participant reconstruction, game initialization, RNG lineage,
probability validation, SHA-guard, no-forecast-metrics). Runtime-dependent checks (D3
reproduction, missing history, short-sequence integration, identity binding, registry
projection) skip cleanly when the governed runtime artifacts are absent. No D3 retraining, no
whole-game Monte Carlo, no betting metrics.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5.pa_provider import (
    CLASS_ORDER,
    D3_STATE_TABLE_SHA,
    PAProviderError,
    PlayerStateResolver,
    _load_verified_json,
    validate_probability_vector,
)
from server.sports_phase5.participant_replay import (
    COMPLETE,
    INCOMPLETE,
    PROVENANCE_LABEL,
    reconstruct_game_participants,
)
from server.sports_phase5.game_initialization import (
    GameInitialization,
    GameInitializationError,
    RngLineage,
    SimulationAuthorities,
)

REPO = Path(__file__).resolve().parents[1]
DYNAMIC_NS = REPO / ".runtime/asp-model-studio/sports-modeling/mlb-dynamic-player-state-v1"
PA_NS = REPO / ".runtime/asp-model-studio/sports-modeling/mlb-pa-v1"
SIM_RECORD = REPO / ".runtime/asp-model-studio/sports-phase5/simulation-input/latest.simulation.json"


# --------------------------------------------------------------------------------------
# Synthetic governed-shaped rows for hermetic participant tests
# --------------------------------------------------------------------------------------
def _lineup(prefix: str) -> list[str]:
    return [f"retrosheet:player:{prefix}{i}" for i in range(1, 10)]


ROLE_CODES = [8, 4, 6, 2, 3, 5, 7, 9, 1]  # slot 4 is the catcher (code 2)


def _synthetic_game_rows() -> list[dict]:
    away = _lineup("a")
    home = _lineup("h")
    away_p = "retrosheet:player:ap1"
    home_p = "retrosheet:player:hp1"
    rows: list[dict] = []
    pn = 0
    base = dict(
        game_id="retrosheet:game:TST202400001", game_date="2024-04-01", season=2024,
        visiting_team_id="retrosheet:team:AAA", home_team_id="retrosheet:team:HHH",
        pbp_quality="FULL", regulation_innings=9, retrosheet_lineup_role_codes=ROLE_CODES,
    )
    # top 1: away bats vs home pitcher (3 outs)
    for slot in range(3):
        pn += 1
        rows.append({**base, "play_number": pn, "inning": 1, "top_bottom": 0,
                     "batting_team_id": "retrosheet:team:AAA", "pitching_team_id": "retrosheet:team:HHH",
                     "batter_id": away[slot], "pitcher_id": home_p, "lineup_player_ids": away,
                     "plate_appearance_id": f"pa-top1-{slot}", "pa_outcome": "BIP_OUT"})
    # bottom 1: home bats vs away pitcher (3 outs)
    for slot in range(3):
        pn += 1
        rows.append({**base, "play_number": pn, "inning": 1, "top_bottom": 1,
                     "batting_team_id": "retrosheet:team:HHH", "pitching_team_id": "retrosheet:team:AAA",
                     "batter_id": home[slot], "pitcher_id": away_p, "lineup_player_ids": home,
                     "plate_appearance_id": f"pa-bot1-{slot}", "pa_outcome": "STRIKEOUT"})
    return rows


# --------------------------------------------------------------------------------------
# Participant replay (hermetic)
# --------------------------------------------------------------------------------------
def test_participant_starting_lineup_and_order():
    gp = reconstruct_game_participants(_synthetic_game_rows())
    assert gp.provenance == PROVENANCE_LABEL
    assert gp.status == COMPLETE
    assert gp.away.starting_lineup == tuple(_lineup("a"))
    assert gp.home.starting_lineup == tuple(_lineup("h"))
    assert gp.away.batting_order == tuple(range(1, 10))


def test_participant_starting_catcher_role_code_two():
    gp = reconstruct_game_participants(_synthetic_game_rows())
    assert gp.away.starting_catcher == "retrosheet:player:a4"  # slot 4 has role code 2
    assert gp.home.starting_catcher == "retrosheet:player:h4"


def test_participant_pitcher_replay():
    gp = reconstruct_game_participants(_synthetic_game_rows())
    assert gp.home.starting_pitcher == "retrosheet:player:hp1"
    assert gp.away.starting_pitcher == "retrosheet:player:ap1"
    assert gp.home.pitcher_sequence == ("retrosheet:player:hp1",)


def test_participant_substitution_replay_detected():
    rows = _synthetic_game_rows()
    # substitute away slot 3 in the bottom-of-first snapshot is irrelevant (home bats); add a
    # top-2 PA with a changed away lineup to exercise substitution detection.
    away = _lineup("a")
    away_sub = list(away)
    away_sub[2] = "retrosheet:player:aX"
    rows.append({
        "game_id": "retrosheet:game:TST202400001", "game_date": "2024-04-01", "season": 2024,
        "visiting_team_id": "retrosheet:team:AAA", "home_team_id": "retrosheet:team:HHH",
        "pbp_quality": "FULL", "regulation_innings": 9, "retrosheet_lineup_role_codes": ROLE_CODES,
        "play_number": 99, "inning": 2, "top_bottom": 0, "batting_team_id": "retrosheet:team:AAA",
        "pitching_team_id": "retrosheet:team:HHH", "batter_id": "retrosheet:player:aX",
        "pitcher_id": "retrosheet:player:hp1", "lineup_player_ids": away_sub,
        "plate_appearance_id": "pa-top2-0", "pa_outcome": "SINGLE"})
    gp = reconstruct_game_participants(rows)
    subs = gp.away.batter_substitutions
    assert any(s["slot"] == 3 and s["incoming"] == "retrosheet:player:aX" for s in subs)


def test_participant_incomplete_when_pbp_not_full():
    rows = _synthetic_game_rows()
    for r in rows:
        r["pbp_quality"] = "PARTIAL"
    gp = reconstruct_game_participants(rows)
    assert gp.status == INCOMPLETE
    assert "PBP_NOT_FULL" in gp.incompleteness_reasons


# --------------------------------------------------------------------------------------
# Game initialization (hermetic)
# --------------------------------------------------------------------------------------
def _authorities() -> SimulationAuthorities:
    return SimulationAuthorities(
        dataset_registration_id="reg", dataset_manifest_sha="man", replay_contract="MLB_GAME_REPLAY_ENGINE_V1",
        transition_contract="MLB_BASE_OUT_TRANSITION_MODEL_V1", transition_model_sha="t",
        pa_provider_contract="D3_PROBABILISTIC_PA_PROVIDER_V1", pa_model_authority="m",
        participant_provider_contract="MLB_HISTORICAL_PARTICIPANT_REPLAY_PROVIDER_V1")


def _init(**overrides) -> GameInitialization:
    kwargs = dict(
        game_id="g", game_date="2024-04-01", season=2024, away_team_id="A", home_team_id="H",
        regulation_innings=9, away_batting_order=tuple(_lineup("a")), home_batting_order=tuple(_lineup("h")),
        away_starting_pitcher="ap", home_starting_pitcher="hp", authorities=_authorities(),
        rng=RngLineage(1, "g"))
    kwargs.update(overrides)
    return GameInitialization(**kwargs)


def test_game_initialization_valid_opener():
    init = _init()
    init.validate()
    s = init.initial_state()
    assert (s.inning, s.top, s.outs, s.base_mask, s.away_score, s.home_score) == (1, True, 0, 0, 0, 0)


def test_invalid_initialization_rejected():
    with pytest.raises(GameInitializationError):
        _init(away_team_id="H").validate()  # same as home
    with pytest.raises(GameInitializationError):
        _init(away_batting_order=tuple(_lineup("a")[:8])).validate()  # not nine
    with pytest.raises(GameInitializationError):
        _init(home_starting_pitcher="").validate()  # missing pitcher


def test_rng_lineage_reproducible_and_divergent():
    a = RngLineage(100, "gameX")
    b = RngLineage(100, "gameX")
    c = RngLineage(101, "gameX")
    assert a.game_seed() == b.game_seed()
    assert a.game_seed() != c.game_seed()
    # independent PA / transition children
    assert a.pa_rng().integers(0, 10_000) == b.pa_rng().integers(0, 10_000)
    assert a.pa_rng().bit_generator.state != a.transition_rng().bit_generator.state


# --------------------------------------------------------------------------------------
# Probability validation + class order (hermetic)
# --------------------------------------------------------------------------------------
def test_class_order_is_frozen_eight():
    assert CLASS_ORDER == (
        "STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH")


def test_probability_validation_rules():
    good = [1.0 / 8] * 8
    ok, warns = validate_probability_vector(good)
    assert ok and warns == ()
    bad_sum = [0.5] * 8
    ok, warns = validate_probability_vector(bad_sum)
    assert not ok and "PROBABILITY_SUM_NOT_ONE" in warns
    negative = [-0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.1, 0.2]
    ok, warns = validate_probability_vector(negative)
    assert not ok and "NEGATIVE_PROBABILITY" in warns
    wrong_len = [0.25] * 4
    ok, warns = validate_probability_vector(wrong_len)
    assert not ok


# --------------------------------------------------------------------------------------
# D3 artifact SHA guard (hermetic, temp files)
# --------------------------------------------------------------------------------------
def test_d3_artifact_sha_guard_rejects_tampered(tmp_path):
    fake_sha = "0" * 64
    obj = tmp_path / "objects" / "sha256" / fake_sha[:2] / fake_sha
    obj.mkdir(parents=True)
    (obj / "model.json").write_bytes(b'{"tampered": true}')  # sha != fake_sha
    with pytest.raises(PAProviderError):
        _load_verified_json(tmp_path, fake_sha, "model.json")


def test_d3_artifact_sha_guard_accepts_matching(tmp_path):
    content = b'{"payload": {"ok": true}}'
    sha = hashlib.sha256(content).hexdigest()
    obj = tmp_path / "objects" / "sha256" / sha[:2] / sha
    obj.mkdir(parents=True)
    (obj / "model.json").write_bytes(content)
    loaded = _load_verified_json(tmp_path, sha, "model.json")
    assert loaded == {"payload": {"ok": True}}


def test_d3_artifact_missing_file_fails_closed(tmp_path):
    with pytest.raises(PAProviderError):
        _load_verified_json(tmp_path, "a" * 64, "model.json")


# --------------------------------------------------------------------------------------
# No forecast / betting metrics in the persisted record
# --------------------------------------------------------------------------------------
@pytest.mark.skipif(not SIM_RECORD.is_file(), reason="simulation-input record not present")
def test_no_game_forecast_or_betting_metrics():
    text = SIM_RECORD.read_text(encoding="utf-8").lower()
    for banned in ("winprobability", "win_probability", "runline", "run_line", "moneyline",
                   "totalprobability", "bettingedge", "betting_edge", "sportsbook", "odds"):
        assert banned not in text, f"forbidden forecast/betting token present: {banned}"


# --------------------------------------------------------------------------------------
# Runtime-dependent: D3 reproduction, missing history, identity binding, short sequence
# --------------------------------------------------------------------------------------
def _runtime_present() -> bool:
    state = DYNAMIC_NS / "objects/sha256" / D3_STATE_TABLE_SHA[:2] / D3_STATE_TABLE_SHA / "mlb-dynamic-player-state-v1.parquet"
    return state.is_file()


@pytest.mark.skipif(not _runtime_present(), reason="governed D3 runtime artifacts not present")
def test_d3_reproduction_sample_bit_exact():
    import pyarrow.parquet as pq
    import glob as _glob
    from server.sports_phase5.pa_provider import D3ProbabilisticPAProvider, PAInvocationContext, D3_FOLD_PREDICTION_SHA
    from server.sports_modeling.metrics import PA_CLASS_ORDER

    state = pq.read_table(str(DYNAMIC_NS / "objects/sha256" / D3_STATE_TABLE_SHA[:2] / D3_STATE_TABLE_SHA / "mlb-dynamic-player-state-v1.parquet")).to_pandas()
    resolver = PlayerStateResolver.from_records(state.to_dict("records"), state_table_sha=D3_STATE_TABLE_SHA)
    provider = D3ProbabilisticPAProvider.from_runtime(dynamic_namespace_root=DYNAMIC_NS, resolver=resolver)
    fv = pq.read_table(_glob.glob(str(PA_NS / "objects/sha256/**/mlb-pa-feature-view-v1.parquet"), recursive=True)[0]).to_pandas()
    sub = fv[fv["season"] == 2024].head(2000).reset_index(drop=True)
    contexts = [PAInvocationContext(
        game_id=str(r.game_id), game_date=str(r.game_date), season=2024, inning=int(r.context_inning),
        top=(int(r.context_top_bottom) == 0), outs_before=int(r.context_outs_before),
        base_mask_before=int(r.context_base_mask_before), batting_score_diff_before=int(r.context_batting_score_diff_before),
        batter_uuid=str(r.batter_canonical_player_uuid), pitcher_uuid=str(r.pitcher_canonical_player_uuid))
        for r in sub.itertuples(index=False)]
    responses = provider.score_batch(contexts)
    probs = np.array([resp.probabilities for resp in responses])
    sha = D3_FOLD_PREDICTION_SHA[2024]
    fp = pq.read_table(str(DYNAMIC_NS / "objects/sha256" / sha[:2] / sha / "dynamic-fold-2024-predictions.parquet")).to_pandas().set_index("plate_appearance_id")
    frozen = fp.loc[sub["plate_appearance_id"].to_numpy(), [f"raw_D3_{c}" for c in PA_CLASS_ORDER]].to_numpy()
    # The full fold scored in one batch (as training scored it) reproduces at exactly 0.0; a
    # sub-batch agrees within BLAS floating-point non-associativity (~1e-16), well within the
    # numerical-tolerance reproduction the D3 contract requires.
    assert np.abs(probs - frozen).max() < 1e-12
    for resp in responses:
        ok, _ = validate_probability_vector(resp.probabilities)
        assert ok
        assert abs(sum(resp.probabilities) - 1.0) < 1e-9
        assert all(p >= 0.0 for p in resp.probabilities)


@pytest.mark.skipif(not SIM_RECORD.is_file(), reason="simulation-input record not present")
def test_persisted_record_reports_passed_gates_and_exact_reproduction():
    payload = json.loads(SIM_RECORD.read_text(encoding="utf-8"))["simulationInput"]
    assert payload["paProvider"]["reproduction"]["exactReproduction"] is True
    assert payload["paProvider"]["reproduction"]["maxAbsProbabilityDiff"] == 0.0
    assert payload["shortSequenceIntegration"]["clean"] is True
    assert payload["shortSequenceIntegration"]["illegalStates"] == 0
    assert payload["shortSequenceIntegration"]["sameSeedReproducible"] is True
    assert payload["shortSequenceIntegration"]["differentSeedDivergent"] is True
    assert payload["monteCarloEntryDecision"]["decision"] == "MONTE_CARLO_ENTRY_GATES_PASSED"
    assert payload["participantProvider"]["provenance"] == PROVENANCE_LABEL


@pytest.mark.skipif(not SIM_RECORD.is_file(), reason="simulation-input record not present")
def test_registry_projection_authority_gated():
    from server.sports_datasets.registry import _load_active_simulation_input
    payload = json.loads(SIM_RECORD.read_text(encoding="utf-8"))["simulationInput"]
    auth = payload["datasetAuthority"]
    good = _load_active_simulation_input({"registration_id": auth["registrationId"], "manifest_sha": auth["manifestSha"]})
    assert good is not None
    assert good["monteCarloEntryDecision"] == "MONTE_CARLO_ENTRY_GATES_PASSED"
    assert _load_active_simulation_input({"registration_id": "x", "manifest_sha": "y"}) is None


@pytest.mark.skipif(not _runtime_present(), reason="governed D3 runtime artifacts not present")
def test_state_table_authority_mismatch_rejected():
    import pyarrow.parquet as pq
    from server.sports_phase5.pa_provider import D3ProbabilisticPAProvider
    state = pq.read_table(str(DYNAMIC_NS / "objects/sha256" / D3_STATE_TABLE_SHA[:2] / D3_STATE_TABLE_SHA / "mlb-dynamic-player-state-v1.parquet")).to_pandas()
    resolver = PlayerStateResolver.from_records(state.to_dict("records"), state_table_sha="deadbeef")
    with pytest.raises(PAProviderError):
        D3ProbabilisticPAProvider.from_runtime(dynamic_namespace_root=DYNAMIC_NS, resolver=resolver)
