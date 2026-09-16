"""Focused pure tests for the producer-side market probability contract."""
import hashlib
import json
from pathlib import Path

import pytest

from server.sports_shared.market_probabilities import (
    MarketProbabilityError,
    JointScorePopulation,
    canonical_json_bytes,
    evaluate_cross_game,
    evaluate_market,
    evaluate_same_game_joint,
)


PACKAGE_SHA = "a" * 64
CELLS = [
    {"awayScore": 0, "homeScore": 0, "count": 1},
    {"awayScore": 1, "homeScore": 0, "count": 1},
    {"awayScore": 0, "homeScore": 1, "count": 1},
    {"awayScore": 2, "homeScore": 1, "count": 1},
    {"awayScore": 1, "homeScore": 2, "count": 1},
    {"awayScore": 3, "homeScore": 0, "count": 1},
    {"awayScore": 0, "homeScore": 3, "count": 1},
    {"awayScore": 2, "homeScore": 2, "count": 1},
]


def population(game_id="game-1", sport="NFL"):
    return JointScorePopulation.from_cells(
        sport=sport,
        game_id=game_id,
        forecast_id=f"forecast-{game_id}",
        model_id="FROZEN_TEST_MODEL",
        configuration_id="SYNTHETIC_GOLDEN_V1",
        package_sha256=PACKAGE_SHA,
        cells=CELLS,
        draw_count=8,
    )


def assert_mass(result):
    assert sum(result["counts"].values()) == result["effectiveDrawCount"]
    assert sum(result["probabilities"].values()) == pytest.approx(1.0)


def test_moneyline_enumeration_and_tie_refund():
    result = evaluate_market(population(), {"market": "MONEYLINE", "selection": "HOME", "tieSettlement": "PUSH"})
    assert result["counts"] == {"win": 3, "loss": 3, "push": 2, "void": 0}
    assert result["probabilities"]["win"] == 3 / 8
    assert result["fairPriceComponents"]["pushAwareFairDecimalOdds"] == 2.0
    assert_mass(result)


def test_spread_orientation_and_exact_signs():
    home_minus_one = evaluate_market(population(), {"market": "SPREAD", "selection": "HOME", "line": -1})
    away_plus_one = evaluate_market(population(), {"market": "SPREAD", "selection": "AWAY", "line": 1})
    assert home_minus_one["counts"] == {"win": 1, "loss": 5, "push": 2, "void": 0}
    assert away_plus_one["counts"] == {"win": 5, "loss": 1, "push": 2, "void": 0}
    assert_mass(home_minus_one)
    assert_mass(away_plus_one)


def test_integer_total_push_and_half_point_no_push():
    integer = evaluate_market(population(), {"market": "TOTAL", "selection": "OVER", "line": 3})
    half = evaluate_market(population(), {"market": "TOTAL", "selection": "UNDER", "line": 2.5})
    assert integer["counts"] == {"win": 1, "loss": 3, "push": 4, "void": 0}
    assert half["counts"] == {"win": 3, "loss": 5, "push": 0, "void": 0}
    assert_mass(integer)
    assert_mass(half)


def test_same_game_intersection_is_not_naive_marginal_product():
    home = {"market": "MONEYLINE", "selection": "HOME", "tieSettlement": "PUSH"}
    over = {"market": "TOTAL", "selection": "OVER", "line": 2.5}
    joint = evaluate_same_game_joint(population(), [home, over])
    home_result = evaluate_market(population(), home)
    over_result = evaluate_market(population(), over)
    assert joint["counts"] == {"win": 2, "loss": 5, "push": 1, "void": 0}
    assert joint["probabilities"]["win"] == 2 / 8
    assert joint["probabilities"]["win"] != home_result["probabilities"]["win"] * over_result["probabilities"]["win"]
    assert joint["method"] == "PER_DRAW_SAME_GAME_INTERSECTION"
    assert_mass(joint)


def test_cross_game_fails_closed_without_joint_population():
    a = evaluate_market(population("game-a"), {"market": "TOTAL", "selection": "OVER", "line": 2.5})
    b = evaluate_market(population("game-b"), {"market": "TOTAL", "selection": "UNDER", "line": 2.5})
    with pytest.raises(MarketProbabilityError, match="CROSS_GAME_JOINT_UNSUPPORTED"):
        evaluate_cross_game([a, b])
    approximation = evaluate_cross_game([a, b], allow_independence_assumption=True)
    assert approximation["status"] == "APPROXIMATE_RESEARCH_ONLY"
    assert approximation["method"] == "INDEPENDENCE_ASSUMPTION"
    assert approximation["effectiveDrawCount"] is None
    assert sum(approximation["probabilities"].values()) == pytest.approx(1.0)


def test_point_only_and_hash_mismatch_fail_closed():
    kwargs = dict(
        sport="NBA", game_id="nba-game", forecast_id="nba-point", model_id="RIDGE_ELO",
        configuration_id="POINT_ONLY", package_sha256=PACKAGE_SHA,
    )
    with pytest.raises(MarketProbabilityError, match="PAIRED_POPULATION_UNAVAILABLE"):
        JointScorePopulation.from_cells(**kwargs, cells=[], draw_count=0)
    with pytest.raises(MarketProbabilityError, match="POPULATION_HASH_MISMATCH"):
        JointScorePopulation.from_cells(**kwargs, cells=CELLS, draw_count=8, expected_population_sha256="b" * 64)


def test_counts_duplicates_and_identity_fail_closed():
    with pytest.raises(MarketProbabilityError, match="DRAW_COUNT_MISMATCH"):
        JointScorePopulation.from_cells(
            sport="MLB", game_id="x", forecast_id="f", model_id="m", configuration_id="c",
            package_sha256=PACKAGE_SHA, cells=CELLS, draw_count=9,
        )
    with pytest.raises(MarketProbabilityError, match="DUPLICATE_SCORE_CELL"):
        JointScorePopulation.from_cells(
            sport="CFB", game_id="x", forecast_id="f", model_id="m", configuration_id="c",
            package_sha256=PACKAGE_SHA, cells=[CELLS[0], CELLS[0]], draw_count=2,
        )


def test_golden_vectors_match_documented_fixture():
    fixture_path = Path("docs/aisp-market-probability-contract-v1/fixtures/golden-vectors.json")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    pop = JointScorePopulation.from_cells(**fixture["population"])
    assert pop.population_sha256 == fixture["expectedPopulationSha256"]
    for vector in fixture["vectors"]:
        if vector["kind"] == "single":
            result = evaluate_market(pop, vector["leg"])
        else:
            result = evaluate_same_game_joint(pop, vector["legs"])
        assert result["counts"] == vector["expectedCounts"]
        assert_mass(result)


def test_unicode_canonicalization_and_library_has_no_side_effect_imports():
    assert canonical_json_bytes({"label": "model — market"}) == b'{"label":"model \xe2\x80\x94 market"}'
    source = Path("server/sports_shared/market_probabilities.py").read_text(encoding="utf-8")
    forbidden = ("requests", "urllib", "subprocess", "sqlite", "psycopg", "boto", "sportsbook")
    assert all(f"import {name}" not in source and f"from {name}" not in source for name in forbidden)
    assert "open(" not in source and "Path(" not in source
