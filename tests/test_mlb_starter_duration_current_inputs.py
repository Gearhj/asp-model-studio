"""Focused current-input regression: unavailable is not no prior history."""
import pytest
from copy import deepcopy
from server.sports_current_statcast.mlb_starter_duration_current_inputs import (
    build_current_duration_inputs, HISTORY_SCHEMA, ELIGIBILITY_DEFINITION, _load_registered_input,
    _protected_history_authorization,
)


def test_current_history_exact_prior_dates_and_no_false_cold_start():
    snapshot = {"game": {"game_id": "g", "starts_at": "2026-09-11T23:00:00Z"},
                "sides": [{"side": side, "starter": {"mlbamId": pid, "observedAt": "2026-09-11T15:00:00Z",
                           "availableAsOf": "2026-09-11T15:00:00Z", "ingestedAt": "2026-09-11T15:00:01Z"}} for side, pid in (("HOME", "1"), ("AWAY", "2"))]}
    coverage = {"completeFrom": "2023-01-01", "completeThrough": "2026-09-10", "allScheduledStartsAccountedFor": True,
                "eligibleStartDefinitionVerified": True, "observedAt": "2026-09-11T14:00:00Z", "availableAsOf": "2026-09-11T14:00:00Z", "ingestedAt": "2026-09-11T14:00:01Z"}
    authority = {"schemaVersion": HISTORY_SCHEMA, "eligibilityDefinition": ELIGIBILITY_DEFINITION,
                 "frozenEligibilityHoldPreserved": True, "playerIdentityMap": {"1": "p", "2": "new"},
                 "coverageByPlayer": {"p": coverage, "new": coverage}}
    rows = [{"startId": "prior", "pitcherId": "p", "gameDate": "2026-09-06", "completionDate": "2026-09-06",
             "availableAsOf": "2026-09-07T12:00:00Z", "observedAt": "2026-09-07T12:00:00Z", "ingestedAt": "2026-09-07T12:00:01Z", "eligible": True, "totalBf": 22},
            {"startId": "sameDay", "pitcherId": "p", "gameDate": "2026-09-11", "completionDate": "2026-09-11",
             "availableAsOf": "2026-09-11T12:00:00Z", "eligible": True, "totalBf": 40}]
    result = build_current_duration_inputs(snapshot, as_of_utc="2026-09-11T18:00:00Z", history_rows=rows, history_authority=authority)
    assert result["status"] == "SUPPORTED"
    assert result["evidenceCutoff"] == "2026-09-11T15:00:01+00:00"
    assert result["home"] == {"homePitcher": 1, "calendarMonth": 9, "priorStartCount": 1, "priorStartBfMean": 22,
                               "daysRest": 4, "historyMissing": False}
    assert result["away"]["priorStartCount"] == 0 and result["away"]["historyMissing"] is True
    assert result["away"]["priorStartBfMean"] is None
    partial = {**authority, "coverageByPlayer": {"p": {**coverage, "completeThrough": "2024-09-30"}, "new": coverage}}
    result = build_current_duration_inputs(snapshot, as_of_utc="2026-09-11T18:00:00Z", history_rows=rows, history_authority=partial)
    assert result["status"] == "UNSUPPORTED" and result["home"] is None
    assert any(r["reason"] == "CURRENT_START_HISTORY_COVERAGE_INCOMPLETE" for r in result["missingReasons"])
    late = [dict(rows[0], availableAsOf="2026-09-12T12:00:00Z")]
    result = build_current_duration_inputs(snapshot, as_of_utc="2026-09-11T18:00:00Z", history_rows=late, history_authority=authority)
    assert result["status"] == "UNSUPPORTED"
    assert any(r["reason"] == "HISTORY_ROW_NOT_AVAILABLE_AT_CUTOFF" for r in result["missingReasons"])
    # Ingestion after provider availability is legitimate, but after the chosen
    # cutoff is not. Protect all three independent clock-validation branches.
    for scope, reason in (("starter", "STARTER_SOURCE_NOT_AVAILABLE_AT_CUTOFF"),
                          ("coverage", "HISTORY_AUTHORITY_NOT_AVAILABLE_AT_CUTOFF"),
                          ("row", "HISTORY_ROW_NOT_AVAILABLE_AT_CUTOFF")):
        changed_snapshot, changed_authority, changed_rows = deepcopy(snapshot), deepcopy(authority), deepcopy(rows)
        target = (changed_snapshot["sides"][0]["starter"] if scope == "starter" else
                  changed_authority["coverageByPlayer"]["p"] if scope == "coverage" else changed_rows[0])
        target["ingestedAt"] = "2026-09-11T18:00:01Z"
        result = build_current_duration_inputs(changed_snapshot, as_of_utc="2026-09-11T18:00:00Z",
                                              history_rows=changed_rows, history_authority=changed_authority)
        assert result["status"] == "UNSUPPORTED"
        assert any(r["reason"] == reason for r in result["missingReasons"])
    # Namespace rejection occurs before opening even the pointer, so an
    # arbitrary mixed-source path cannot enter the history loader.
    with pytest.raises(ValueError, match="HISTORY_POINTER_OUTSIDE_RESEARCH_NAMESPACE"):
        _load_registered_input("C:/not-authorized/mixed-evaluation.parquet")


def test_three_game_exception_input_scope_and_no_unrelated_protected_rows():
    """Synthetic BF values test input plumbing only; no protected source read."""
    from server.sports_current_statcast.mlb_starter_duration_quarantine import load_exception_authority
    exception = load_exception_authority()  # Authorization/quarantine metadata only.
    clocks = {"observedAt": "2026-09-11T20:00:00Z", "availableAsOf": "2026-09-11T20:00:00Z", "ingestedAt": "2026-09-11T20:00:01Z"}
    coverage = {"completeFrom": "2023-01-01", "completeThrough": "2026-09-10", "allScheduledStartsAccountedFor": True,
                "eligibleStartDefinitionVerified": True, **clocks}
    descriptor = {"pitcherMlbamId": "664285", "gamePk": 823343, "gameDate": "2026-08-17"}
    authority = {"schemaVersion": HISTORY_SCHEMA, "eligibilityDefinition": ELIGIBILITY_DEFINITION,
                 "frozenEligibilityHoldPreserved": True, "playerIdentityMap": {"664285": "p", "690279": "new"},
                 "coverageByPlayer": {"p": coverage, "new": coverage}, "protectedStartPayloadCount": 1,
                 "protectedStartDescriptors": [descriptor], "protectedExceptionAuthority": exception["authorityRef"],
                 "wholeGameQuarantine": exception["quarantineRef"]}
    snapshot = {"game": {"game_id": "synthetic-g", "starts_at": "2026-09-11T23:00:00Z"},
                "sides": [{"side": s, "starter": {"mlbamId": p, **clocks}} for s,p in (("HOME", "664285"), ("AWAY", "690279"))]}
    row = {"startId": "synthetic-start", "pitcherId": "p", **descriptor, "completionDate": "2026-08-17", "eligible": True,
           "totalBf": 17, **clocks}
    result = build_current_duration_inputs(snapshot, as_of_utc="2026-09-11T21:00:00Z", history_rows=[row], history_authority=authority)
    assert result["status"] == "SUPPORTED" and result["home"]["priorStartBfMean"] == 17
    wrong = {**row, "gamePk": 823344}
    result = build_current_duration_inputs(snapshot, as_of_utc="2026-09-11T21:00:00Z", history_rows=[wrong], history_authority=authority)
    assert result["status"] == "UNSUPPORTED" and result["home"] is None
    with pytest.raises(ValueError, match="AUTHORITY_OR_QUARANTINE_MISMATCH"):
        _protected_history_authorization({**authority, "wholeGameQuarantine": {}})
    with pytest.raises(ValueError, match="PROTECTED_GAME_OUTSIDE_THREE_GAME_EXCEPTION"):
        _protected_history_authorization({**authority, "protectedStartDescriptors": [{**descriptor, "gamePk": 823344}]})
