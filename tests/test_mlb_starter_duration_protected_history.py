"""New intake must not inherit the separate V18 rolling-history exception."""
from server.sports_current_statcast.mlb_starter_duration_current_inputs import (
    build_current_duration_inputs, HISTORY_SCHEMA, ELIGIBILITY_DEFINITION,
)


def test_protected_duration_history_never_becomes_supported_from_generic_authority():
    clocks = {"observedAt": "2026-09-11T18:00:00Z", "ingestedAt": "2026-09-11T18:00:01Z",
              "availableAsOf": "2026-09-11T18:00:01Z"}
    snapshot = {"game": {"game_id": "synthetic", "starts_at": "2026-09-11T23:00:00Z"},
                "sides": [{"side": s, "starter": {"mlbamId": p, **clocks}}
                          for s, p in (("HOME", "1"), ("AWAY", "2"))]}
    coverage = {"completeFrom": "2023-01-01", "completeThrough": "2026-09-10",
                "allScheduledStartsAccountedFor": True, "eligibleStartDefinitionVerified": True, **clocks}
    authority = {"schemaVersion": HISTORY_SCHEMA, "eligibilityDefinition": ELIGIBILITY_DEFINITION,
                 "frozenEligibilityHoldPreserved": True, "playerIdentityMap": {"1": "p1", "2": "p2"},
                 "coverageByPlayer": {"p1": coverage, "p2": coverage},
                 "sourcePurpose": "CURRENT_PREGAME_INPUTS_ONLY"}
    rows = [{"startId": "synthetic-protected", "pitcherId": "p1", "gameDate": "2026-08-20",
             "completionDate": "2026-08-20", "eligible": True, "totalBf": 20, **clocks}]
    result = build_current_duration_inputs(snapshot, as_of_utc="2026-09-11T18:30:00Z",
                                           history_rows=rows, history_authority=authority)
    assert result["status"] == "UNSUPPORTED" and result["home"] is None
    assert any(r["reason"] == "PROTECTED_START_HISTORY_PROSPECTIVE_USE_NOT_AUTHORIZED"
               for r in result["missingReasons"])
