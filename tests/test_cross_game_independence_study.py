from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cross_game_independence_study", ROOT / "scripts" / "cross_game_independence_study.py"
)
assert SPEC and SPEC.loader
STUDY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STUDY)


def game(key: str, sport: str, home: str, away: str, start: str) -> dict[str, object]:
    row: dict[str, object] = {
        "sport": sport,
        "game_key": key,
        "slate_date": "2024-09-07",
        "start_time": pd.Timestamp(start),
        "start_time_certified": True,
        "home_team": home,
        "away_team": away,
        "regular_season": True,
        "postseason": False,
        "home_leg_class": "FAVORITE",
        "p_home": 0.6,
        "actual_home_win": 1.0,
        "p_favorite": 0.6,
        "actual_favorite_win": 1.0,
    }
    for metric in STUDY.RESIDUALS:
        row[metric] = 0.1
    return row


def test_pair_construction_is_unique_and_never_same_game() -> None:
    games = pd.DataFrame([
        game("CFB:1", "CFB", "A", "B", "2024-09-07 12:00"),
        game("CFB:2", "CFB", "C", "D", "2024-09-07 13:00"),
        game("NFL:3", "NFL", "E", "F", "2024-09-07 16:30"),
    ])
    pairs = STUDY.pair_rows(games)
    assert len(pairs) == 3
    assert pairs.pair_id.nunique() == 3
    assert not (pairs.game_a == pairs.game_b).any()
    assert all(left < right for left, right in zip(pairs.game_a, pairs.game_b))


def test_shared_team_and_timing_are_explicit() -> None:
    games = pd.DataFrame([
        game("NFL:1", "NFL", "A", "B", "2024-09-07 12:00"),
        game("NFL:2", "NFL", "C", "A", "2024-09-07 12:45"),
        game("NFL:3", "NFL", "D", "E", "2024-09-07 16:30"),
    ])
    pairs = STUDY.pair_rows(games).set_index("pair_id")
    assert bool(pairs.loc["NFL:1|NFL:2", "shared_team"])
    assert pairs.loc["NFL:1|NFL:2", "timing_class"] == "SAME_START_WINDOW"
    assert pairs.loc["NFL:1|NFL:3", "timing_class"] == "SEPARATED_START"


def test_whole_slate_bootstrap_is_deterministic() -> None:
    frame = pd.DataFrame({"slate_date": ["a", "a", "b", "b"], "x": [0.1, 0.2, -0.1, 0.0]})
    first = STUDY._cluster_bootstrap(frame, frame.x.to_numpy(), 17)
    second = STUDY._cluster_bootstrap(frame, frame.x.to_numpy(), 17)
    assert first == second
    coverage = STUDY.cluster_coverage(frame)
    assert coverage["independentSlateClusters"] == 2
    assert coverage["kishEffectiveSlatesForPairWeightedEstimate"] == 2.0


def test_canonical_json_rejects_false_numeric_precision() -> None:
    encoded = STUDY.canonical({"finite": 1.0, "unsupported": math.nan})
    assert encoded == b'{"finite":1.0,"unsupported":null}'


def test_script_has_no_external_or_consumer_clients() -> None:
    source = (ROOT / "scripts" / "cross_game_independence_study.py").read_text(encoding="utf-8")
    for forbidden in ("requests", "httpx", "SportsGameOdds", "The Odds API", "asp-model-exchange"):
        assert forbidden not in source
    assert '"providerCalls": 0' in source
    assert '"aispWrites": 0' in source
    assert '"sealedReads": 0' in source
