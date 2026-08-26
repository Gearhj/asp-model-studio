from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from server.sports_gold.contracts import (
    ADVANCED_FEATURES,
    BATTER_HISTORY_FEATURES,
    EXPECTED_DEVELOPMENT_ROWS,
    EXPECTED_SEASON_ROWS,
    EXPECTED_VALIDATION_ROWS,
    GOLD_FEATURES,
    MATCHUP_FEATURES,
    PITCHER_HISTORY_FEATURES,
)
from server.sports_gold.features import (
    assemble_gold_frame,
    build_advanced_features,
    prepare_pa_history,
)
from server.sports_gold.models import run_fixed_experiment_suite
from server.sports_gold.pa_bridge import bridge_plate_appearances
from server.sports_gold.silver_inputs import GoldInputError, VerifiedSilverHandle, read_verified_columns
from server.sports_modeling.feature_contract import FEATURE_NAMES
from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix


def _bridge_fixture():
    target = pd.DataFrame([
        {
            "plate_appearance_id": "retrosheet:pa:AAA202104010:1", "game_id": "retrosheet:game:AAA202104010",
            "season": 2021, "batter_canonical_player_uuid": "b-uuid", "pitcher_canonical_player_uuid": "p-uuid",
            "context_inning": 1, "context_top_bottom": 0, "outcome": "STRIKEOUT",
        },
        {
            "plate_appearance_id": "retrosheet:pa:AAA202104010:5", "game_id": "retrosheet:game:AAA202104010",
            "season": 2021, "batter_canonical_player_uuid": "b-uuid", "pitcher_canonical_player_uuid": "p-uuid",
            "context_inning": 1, "context_top_bottom": 0, "outcome": "HOME_RUN",
        },
        {
            "plate_appearance_id": "retrosheet:pa:MISS202404010:1", "game_id": "retrosheet:game:MISS202404010",
            "season": 2024, "batter_canonical_player_uuid": "b-uuid", "pitcher_canonical_player_uuid": "p-uuid",
            "context_inning": 1, "context_top_bottom": 0, "outcome": "WALK_HBP_CI",
        },
    ])
    silver = pd.DataFrame([
        {"canonicalPaId": "spa-0", "canonicalGameId": "game-a", "atBatNumber": "0",
         "batterCanonicalPlayerId": "b", "pitcherCanonicalPlayerId": "p", "season": "2021",
         "inning": "1", "inningTopBot": "Top"},
        {"canonicalPaId": "spa-4", "canonicalGameId": "game-a", "atBatNumber": "4",
         "batterCanonicalPlayerId": "b", "pitcherCanonicalPlayerId": "p", "season": "2021",
         "inning": "1", "inningTopBot": "Top"},
    ])
    games = pd.DataFrame([
        {"retrosheetGameId": "AAA202104010", "canonicalGameId": "game-a", "resolutionStatus": "MATCHED_EXACT"}
    ])
    players = pd.DataFrame([
        {"chadwickKeyUuid": "b-uuid", "canonicalPlayerId": "b", "resolutionStatus": "MATCHED_EXACT"},
        {"chadwickKeyUuid": "p-uuid", "canonicalPlayerId": "p", "resolutionStatus": "MATCHED_EXACT"},
    ])
    return target, silver, games, players


def _history_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = [
        {"canonicalPaId": "old", "canonicalGameId": "g0", "mlbamGamePk": "1", "atBatNumber": "0",
         "batterCanonicalPlayerId": "b", "pitcherCanonicalPlayerId": "p", "season": "2020",
         "gameDate": "2020-09-01", "stand": "L", "pThrows": "R", "paEvent": "strikeout"},
        {"canonicalPaId": "current", "canonicalGameId": "g1", "mlbamGamePk": "2", "atBatNumber": "0",
         "batterCanonicalPlayerId": "b", "pitcherCanonicalPlayerId": "p", "season": "2021",
         "gameDate": "2021-04-01", "stand": "L", "pThrows": "R", "paEvent": "home_run"},
        {"canonicalPaId": "same-day", "canonicalGameId": "g1", "mlbamGamePk": "2", "atBatNumber": "1",
         "batterCanonicalPlayerId": "b", "pitcherCanonicalPlayerId": "p", "season": "2021",
         "gameDate": "2021-04-01", "stand": "L", "pThrows": "R", "paEvent": "walk"},
        {"canonicalPaId": "future", "canonicalGameId": "g2", "mlbamGamePk": "3", "atBatNumber": "0",
         "batterCanonicalPlayerId": "b", "pitcherCanonicalPlayerId": "p", "season": "2021",
         "gameDate": "2021-04-02", "stand": "L", "pThrows": "R", "paEvent": "walk"},
    ]
    pitch = pd.DataFrame([
        {"canonicalPaId": "old", "pitch_count": 2, "swing_count": 1, "whiff_count": 1,
         "contact_count": 0, "fastball_count": 2, "breaking_count": 0, "offspeed_count": 0,
         "fastball_velocity_sum": 190.0, "fastball_velocity_count": 2},
        {"canonicalPaId": "current", "pitch_count": 1, "swing_count": 1, "whiff_count": 0,
         "contact_count": 1, "fastball_count": 1, "breaking_count": 0, "offspeed_count": 0,
         "fastball_velocity_sum": 99.0, "fastball_velocity_count": 1},
        {"canonicalPaId": "same-day", "pitch_count": 1, "swing_count": 1, "whiff_count": 0,
         "contact_count": 1, "fastball_count": 0, "breaking_count": 1, "offspeed_count": 0,
         "fastball_velocity_sum": 0.0, "fastball_velocity_count": 0},
        {"canonicalPaId": "future", "pitch_count": 1, "swing_count": 1, "whiff_count": 0,
         "contact_count": 1, "fastball_count": 0, "breaking_count": 0, "offspeed_count": 1,
         "fastball_velocity_sum": 0.0, "fastball_velocity_count": 0},
    ])
    history = prepare_pa_history(pd.DataFrame(rows), pitch)
    matched = pd.DataFrame([{"canonicalPaId": "current"}])
    return history, matched


def _model_frame() -> pd.DataFrame:
    rng = np.random.default_rng(20260819)
    rows: list[dict] = []
    for season in (2021, 2022, 2023, 2024):
        for repeat in range(2):
            for class_index, outcome in enumerate(PA_CLASS_ORDER):
                row = {name: float(rng.normal()) for name in GOLD_FEATURES}
                row["context_top_bottom"] = float((class_index + repeat) % 2)
                row["context_outs_before"] = float((class_index + repeat) % 3)
                row["context_base_mask_before"] = float((class_index + 2 * repeat) % 8)
                row.update({"season": season, "outcome": outcome})
                rows.append(row)
    return pd.DataFrame(rows)


def test_exact_pa_bridge_is_one_to_one_and_fail_closed():
    target, silver, games, players = _bridge_fixture()
    result = bridge_plate_appearances(target, silver, games, players)
    assert result.matched["canonicalPaId"].tolist() == ["spa-0", "spa-4"]
    assert result.matched["occurrenceResolved"].tolist() == [True, True]
    assert result.exclusions["reasonCode"].tolist() == ["GAME_IDENTITY_UNMAPPED"]
    assert result.report["outcomeColumnsUsed"] == []
    assert result.report["counts"]["duplicateOutputCanonicalPaIds"] == 0


def test_gold_row_key_is_unique():
    base = _model_frame().iloc[:2].copy()
    base.insert(0, "canonicalPaId", ["pa1", "pa2"])
    base.insert(1, "plate_appearance_id", ["r1", "r2"])
    base.insert(2, "canonicalGameId", ["g1", "g1"])
    base.insert(3, "game_id", ["rg1", "rg1"])
    base.insert(4, "game_date", ["2021-04-01", "2021-04-01"])
    base.insert(7, "batterCanonicalPlayerId", ["b1", "b2"])
    base.insert(8, "pitcherCanonicalPlayerId", ["p1", "p1"])
    advanced = base.loc[:, ADVANCED_FEATURES].copy()
    matched = base.drop(columns=list(ADVANCED_FEATURES))
    out = assemble_gold_frame(matched, advanced)
    assert len(out) == 2 and out["canonicalPaId"].is_unique and out["plate_appearance_id"].is_unique


def test_features_use_only_previous_completed_days():
    history, matched = _history_fixture()
    original = build_advanced_features(history, matched)
    mutated = history.copy()
    mutated.loc[mutated["canonicalPaId"].isin(["current", "same-day", "future"]),
                ["_strikeout", "_walk_hbp", "_walk", "swing_count", "whiff_count", "contact_count"]] = 999.0
    changed = build_advanced_features(mutated, matched)
    pd.testing.assert_frame_equal(original, changed, check_exact=True)
    assert original.loc[0, "batter_prior_pa_count"] == 1.0
    assert original.loc[0, "batter_last100_whiff_rate"] == 1.0


def test_gold_features_are_deterministic():
    history, matched = _history_fixture()
    first = build_advanced_features(history, matched)
    second = build_advanced_features(history.sample(frac=1.0, random_state=7), matched)
    pd.testing.assert_frame_equal(first, second, check_exact=True)


def test_2025_is_rejected_before_any_opener_call(monkeypatch, tmp_path: Path):
    calls: list[object] = []
    monkeypatch.setattr("server.sports_gold.silver_inputs.ds.dataset", lambda *a, **k: calls.append(a))
    handle = VerifiedSilverHandle(
        table_name="x", dataset_version_id="x", registration_sha256="a" * 64,
        manifest_sha256="b" * 64, partitioned=True, seasons=(2021, 2022, 2023, 2024),
        row_count=1, object_dir=tmp_path, child_paths=(tmp_path / "never.parquet",), value_digest_sha256=None,
    )
    with pytest.raises(GoldInputError, match="boundary|prohibited"):
        read_verified_columns(handle, ["season"], seasons=(2025,))
    assert calls == []


def test_train_validation_seasons_and_counts_are_exact():
    assert sum(EXPECTED_SEASON_ROWS[s] for s in (2021, 2022, 2023)) == EXPECTED_DEVELOPMENT_ROWS == 547_835
    assert EXPECTED_SEASON_ROWS[2024] == EXPECTED_VALIDATION_ROWS == 182_449
    frame = _model_frame()
    result = run_fixed_experiment_suite(
        frame, base_features=FEATURE_NAMES, batter_features=BATTER_HISTORY_FEATURES,
        pitcher_features=PITCHER_HISTORY_FEATURES, matchup_features=MATCHUP_FEATURES, include_xgboost=False,
    )
    assert result.development_rows == 48 and result.validation_rows == 16


def test_probability_shape_and_frozen_class_order():
    frame = _model_frame()
    result = run_fixed_experiment_suite(
        frame, base_features=FEATURE_NAMES, batter_features=BATTER_HISTORY_FEATURES,
        pitcher_features=PITCHER_HISTORY_FEATURES, matchup_features=MATCHUP_FEATURES, include_xgboost=False,
    )
    assert result.class_order == PA_CLASS_ORDER
    for probabilities in result.probabilities.values():
        assert validate_probability_matrix(probabilities).shape == (16, 8)


def test_fixed_model_suite_end_to_end_small_fixture():
    frame = _model_frame()
    result = run_fixed_experiment_suite(
        frame, base_features=FEATURE_NAMES, batter_features=BATTER_HISTORY_FEATURES,
        pitcher_features=PITCHER_HISTORY_FEATURES, matchup_features=MATCHUP_FEATURES, include_xgboost=False,
    )
    by_id = {row["modelId"]: row for row in result.leaderboard}
    for model_id in ("null", "base_logistic", "gold_logistic", "gold_hgb", "gold_extra_trees", "gold_ensemble"):
        assert by_id[model_id]["status"] == "SUCCESS", by_id[model_id]
    assert by_id["gold_xgboost"]["status"] == "SKIPPED"
    members = by_id["gold_ensemble"]["effectiveConfig"]["memberIds"]
    expected = np.mean(np.stack([result.probabilities[name] for name in members]), axis=0)
    np.testing.assert_allclose(result.probabilities["gold_ensemble"], expected, rtol=0.0, atol=1e-15)
    assert set(result.ablations) == {"base", "base+batter", "base+pitcher", "full"}
