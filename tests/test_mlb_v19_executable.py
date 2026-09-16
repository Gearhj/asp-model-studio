import pandas as pd

from server.sports_current_statcast.mlb_v19_executable import prospective_readiness


def test_executable_fixture_does_not_award_current_readiness_to_stale_history():
    # Deliberately incomplete synthetic authority; no source or estimator loads.
    fields = [f"raw_{n}" for n in range(246)]
    rows = pd.DataFrame([{**{name: 0. for name in fields}, "canonicalGameId": "synthetic-game",
        "batterCanonicalPlayerId": "b", "pitcherCanonicalPlayerId": "p", "battingTeamId": "A", "fieldingTeamId": "H"}])
    authority = {"schemaVersion": "MLB_V19_PROSPECTIVE_INPUT_AUTHORITY_V1", "orderedRawFeatures": fields,
        "historicalTemplatesBorrowed": False, "genericImputation": False, "sourceArtifacts": [],
        "events": [{"canonicalGameId": "synthetic-game", "officialGameDate": "2026-09-11",
            "evidenceCutoff": "2026-09-11T17:00:00Z", "scheduledStartUtc": "2026-09-11T23:00:00Z", "status": "SCHEDULED",
            "semanticHistory": {"completeThrough": "2026-08-06", "coverageComplete": True, "missingDates": [], "sourceFailure": False}}]}
    result = prospective_readiness(rows, authority, fields, as_of_utc="2026-09-11T18:00:00Z")
    reasons = {row["reason"] for row in result["blockers"]}
    assert "SEMANTIC_HISTORY_NOT_COMPLETE_THROUGH_PRIOR_LOCAL_DATE" in reasons
    assert "IMMUTABLE_SOURCE_CHECKSUM_LINEAGE_MISSING" in reasons
    assert not result["sourceConditionsSatisfied"]
    assert not result["publicationAuthorizedByThisCheck"]
    assert not result["executionAllowedInAISP"]
    assert not result["wageringAuthority"]
