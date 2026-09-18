from pathlib import Path

import pytest

from server.sports_nba_gen2.team_box_study import (
    TeamBoxIntegrityError,
    build_pregame_box_features,
    load_governed_population,
)


RECEIPT = Path(r"C:\Users\james\asp-data-staging\nba\gen2-team-box-v1\acquisition-receipt.json")


@pytest.mark.skipif(not RECEIPT.exists(), reason="private retained NBA acquisition is not present")
def test_source_defect_requires_exact_integrity_quarantine():
    with pytest.raises(TeamBoxIntegrityError, match="predeclared integrity quarantine"):
        load_governed_population(RECEIPT)


@pytest.mark.skipif(not RECEIPT.exists(), reason="private retained NBA acquisition is not present")
def test_governed_population_preserves_rebound_semantics_and_schedule_minutes():
    population = load_governed_population(RECEIPT, excluded_integrity_game_ids=("401704652",))
    audit = population.audit
    assert audit["duplicateTeamGameKeys"] == 0
    assert audit["orphanOpponentJoins"] == 0
    assert audit["opponentScoreFailures"] == 0
    assert audit["orphanScheduleRows"] == 0
    assert audit["integrityQuarantineGameIds"] == ["401704652"]
    assert audit["totalReboundIdentity"]["differentRows"] > 0
    assert audit["totalReboundIdentity"]["featureUse"].startswith("OREB and DREB directly")
    assert population.team_rows.team_minutes_derived.notna().all()
    assert (population.team_rows.team_minutes_derived ==
            240 + 25 * population.team_rows.overtime_periods).all()
    assert "total_rebounds" in population.team_rows
    assert "component_rebounds" in population.team_rows


@pytest.mark.skipif(not RECEIPT.exists(), reason="private retained NBA acquisition is not present")
def test_pregame_features_exclude_target_and_same_date_results():
    population = load_governed_population(RECEIPT, excluded_integrity_game_ids=("401704652",))
    features, audit = build_pregame_box_features(population)
    assert audit["sameDateOutcomesConsumed"] is False
    assert audit["targetLeakageChecks"]["latestHistoryBeforeTarget"] is True
    for side in ("home", "away"):
        latest = features[f"{side}_box_feature_history_latest_date"]
        assert ((latest.isna()) | (latest < features.game_date)).all()
    assert not features.box_game_id.astype(str).eq("401704652").any()
    assert features.duplicated("box_game_id").sum() == 0
