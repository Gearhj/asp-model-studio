from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from server.sports_cfb_gen1.pipeline import frequency_rows, simulate_paired_residuals


ROOT = Path(__file__).resolve().parents[1] / "outputs" / "cfb-gen1-v1" / "data"
MODEL = "ridge_alpha100"


def test_retained_population_identity_chronology_and_postponement() -> None:
    games = pd.read_parquet(ROOT / "admitted-games.parquet")
    features = pd.read_parquet(ROOT / "point-in-time-features.parquet")

    assert games["game_id"].is_unique
    assert games["identity_supported"].all()
    assert (games.loc[games["primary"], "both_fbs"]).all()
    assert (~games.loc[games["primary"], "either_exhibition"]).all()
    assert (games.loc[games["primary"], "season_type"] == 2).all()
    assert (games.loc[games["primary"], "week"] <= 14).all()
    assert (
        features["feature_max_source_game_date"].isna()
        | (features["feature_max_source_game_date"] < features["scheduled_at"])
    ).all()

    pair = games[games["game_id"].isin([400767534, 400835430])].sort_values("scheduled_at")
    assert pair["status"].tolist() == ["STATUS_POSTPONED", "STATUS_FINAL"]
    assert pair["primary"].tolist() == [False, True]
    assert pair[["home_score", "away_score"]].iloc[1].tolist() == [52, 3]


def test_joint_residual_simulation_is_deterministic_and_accounted() -> None:
    predictions = pd.read_parquet(ROOT / "season-forward-predictions.parquet")
    target = predictions[predictions["season"].eq(2020)].iloc[0]
    donors = predictions[predictions["scheduled_at"] < target["scheduled_at"]]

    first, first_accounting = simulate_paired_residuals(
        target, donors, MODEL, draw_count=512, low_total_threshold=34, high_total_threshold=80
    )
    second, second_accounting = simulate_paired_residuals(
        target, donors, MODEL, draw_count=512, low_total_threshold=34, high_total_threshold=80
    )

    assert_frame_equal(first, second, check_exact=True)
    assert first_accounting == second_accounting
    assert len(first) == 512
    assert (first[["home_score", "away_score"]].to_numpy() >= 0).all()
    assert (first["home_score"] != first["away_score"]).all()
    assert first_accounting["finalTieCount"] == 0
    assert pd.Timestamp(first_accounting["donorLatestKickoff"]) < target["scheduled_at"]

    frequencies = frequency_rows(int(target["game_id"]), first)
    assert (frequencies.groupby("metric")["count"].sum() == 512).all()
    assert set(frequencies["metric"]) == {"home_score", "away_score", "total", "home_margin"}
