from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast.mlb_v18_current_features import (
    calculate_current_player_features, calculate_current_context, reconcile_field_contract,
    compose_current_game, feature_family, accepted_handedness,
)
from server.sports_current_statcast.contextual_features import GameContextInput, VenueAuthority, build_team_game_context


def _source():
    return {"sourceIdentity": "SYNTHETIC_TEST", "observedAt": "2024-01-02T22:00:00+00:00",
            "availableAsOf": "2024-01-02T23:00:00+00:00", "ingestedAt": "2024-01-02T23:00:00+00:00",
            "completionConfirmedAt": "2024-01-02T21:00:00+00:00", "status": "FINAL",
            "completeFrom": "2024-01-01", "completeThrough": "2024-01-02", "allHistoryComplete": True,
            "contiguousRequestedDatesComplete": True, "missingDates": [],
            "requestedDates": ["2024-01-01", "2024-01-02"]}


def test_current_player_exact_counts_float_velocity_and_gap_not_cold_start():
    source = _source()
    target = pd.DataFrame([{"canonicalPaId": "SIM:target", "canonicalGameId": "target", "gameDate": "2024-01-03",
                           "batterCanonicalPlayerId": "b", "pitcherCanonicalPlayerId": "p", "stand": "L", "pThrows": "R"}])
    pas = pd.DataFrame([{**source, "canonicalPaId": f"pa{i}", "canonicalGameId": "prior", "gameDate": "2024-01-02",
                        "mlbamGamePk": 1, "atBatNumber": i+1, "batterCanonicalPlayerId": "b", "pitcherCanonicalPlayerId": "p",
                        "season": 2024, "stand": "L", "pThrows": "R", "paEvent": "strikeout" if i % 2 else "single"}
                       for i in range(250)])
    pitches = pd.DataFrame([{**source, "canonicalPaId": f"pa{i}", "gameDate": "2024-01-02", "pitchType": kind,
                             "releaseSpeed": velocity, "pitchResultType": result} for i in range(250)
                            for kind, velocity, result in (("FF", 93.125, "swinging_strike"), (None, None, "ball"))])
    metrics = {"AB": 100, "BB": 10, "HBP": 2, "SF": 3, "SH": 1, "H": 30, "2B": 5, "3B": 1, "HR": 4, "SO": 25,
               "BFP": 200, "IPouts": 150, "GS": 8, "G": 10}
    priors = [{**source, "canonicalPlayerId": player, "domain": domain, "season": 2023, "eligibleFromSeason": 2024,
               "metrics": metrics} for player, domain in (("b", "BATTING"), ("p", "PITCHING"))]
    actual, receipt = calculate_current_player_features(target, pas, pitches, as_of_utc="2024-01-03T18:00:00Z",
                                                        history_authority=source, annual_priors=priors)
    assert len(actual.columns) == 56 and len(set(actual.columns)) == 56
    assert actual.iloc[0].batter_last100_pa_count == 100
    assert actual.iloc[0].pitcher_last250_bf_count == 250
    assert actual.iloc[0].pitcher_prior_bf_count == 250
    assert actual.iloc[0].pitcher_last250_pitch_count == 500
    assert actual.iloc[0].pitcher_last250_other_or_unclassified_pitch_count == 250
    assert actual.iloc[0].pitcher_last250_fastball_velocity_sum == 93.125*250
    assert actual.pitcher_last250_fastball_velocity_sum.dtype == np.float64
    assert actual.iloc[0].batter_avg == .3
    assert actual.iloc[0].pitcher_gs_per_g == .8
    assert not receipt["genericImputation"]
    # Concrete live failure: a confirmed player has source-null batting hand.
    # Compare all six flags to the accepted Gold builder, not an invented hand.
    from server.sports_gold.features import (
        prepare_pa_history, aggregate_pitch_history, build_advanced_features_with_sufficient_statistics,
    )
    import pyarrow as pa
    missing_hand_target = {**pas.iloc[0].to_dict(), **target.iloc[0].to_dict(), "stand": None}
    hand_history = prepare_pa_history(pd.concat([pas, pd.DataFrame([missing_hand_target])], ignore_index=True),
        aggregate_pitch_history(pa.Table.from_pandas(pitches, preserve_index=False)), allowed_seasons=(2024,))
    gold, _ = build_advanced_features_with_sufficient_statistics(hand_history, target[["canonicalPaId"]])
    hand_values = accepted_handedness(pd.DataFrame([missing_hand_target]))
    pd.testing.assert_frame_equal(hand_values, gold[hand_values.columns])
    assert hand_values.iloc[0].matchup_batter_hand_missing == 1
    assert hand_values.iloc[0].matchup_platoon_advantage == 0
    incomplete, note = calculate_current_player_features(target, pas.iloc[:80], pitches.iloc[:160],
        as_of_utc="2024-01-03T18:00:00Z", history_authority={**source, "allHistoryComplete": False, "sealedGap": "SYNTHETIC_GAP"},
        annual_priors=priors)
    assert np.isnan(incomplete.iloc[0].pitcher_last250_bf_count)
    assert np.isnan(incomplete.iloc[0].pitcher_last250_insufficient)
    assert all(row["status"] == "INCOMPLETE_WINDOW_NOT_COLD_START" for row in note["rows"])
    # A verified per-player extract may contain all 80 prior PAs without claiming
    # the complete global archive. Exact independent exposure must reconcile.
    sparse_authority = {**source, "allHistoryComplete": False,
        "completeWindowPlayers": {"batter": ["b"], "pitcher": ["p"]},
        "cumulativeExposure": {role: {player: {**source, "value": 80}}
            for role, player in (("batter", "b"), ("pitcher", "p"))}}
    sparse, sparse_note = calculate_current_player_features(target, pas.iloc[:80], pitches.iloc[:160],
        as_of_utc="2024-01-03T18:00:00Z", history_authority=sparse_authority, annual_priors=priors)
    assert sparse.iloc[0].pitcher_last250_bf_count == sparse.iloc[0].batter_last100_pa_count == 80
    assert all(row["completePlayerWindowVerified"] for row in sparse_note["rows"])
    sparse_authority["cumulativeExposure"]["pitcher"]["p"]["value"] = 90
    incomplete_sparse, _ = calculate_current_player_features(target, pas.iloc[:80], pitches.iloc[:160],
        as_of_utc="2024-01-03T18:00:00Z", history_authority=sparse_authority, annual_priors=priors)
    assert np.isnan(incomplete_sparse.iloc[0].pitcher_last250_bf_count)
    assert incomplete_sparse.iloc[0].pitcher_prior_bf_count == 90
    cross_boundary_authority = {**sparse_authority, "completeFrom": "2024-01-02", "requestedDates": ["2024-01-02"],
        "cumulativeExposure": {role: {player: {**source, "value": 250}}
            for role, player in (("batter", "b"), ("pitcher", "p"))}}
    cross_boundary, cross_note = calculate_current_player_features(target, pas.assign(gameDate="2024-01-01"),
        pitches.assign(gameDate="2024-01-01"), as_of_utc="2024-01-03T18:00:00Z",
        history_authority=cross_boundary_authority, annual_priors=priors)
    assert cross_boundary.iloc[0].pitcher_last250_bf_count == 250
    assert all(row["windowSupported"] and row["observedPAsAfterCompleteFrom"] == 0 for row in cross_note["rows"])
    # Enough observed rows, full-history and verified-debut claims cannot hide
    # an uncaptured intermediate date or turn an unseen player into known cold.
    two_targets = pd.concat([target, target.assign(canonicalPaId="SIM:new", batterCanonicalPlayerId="new-b",
                                                   pitcherCanonicalPlayerId="new-p")], ignore_index=True)
    gap_source = {**source, "completeFrom": "2023-12-31",
        "requestedDates": ["2023-12-31", "2024-01-01", "2024-01-02"],
        "missingDates": ["2024-01-01"], "contiguousRequestedDatesComplete": False,
        "verifiedDebutSinceCompleteFrom": {"batter": ["new-b"], "pitcher": ["new-p"]}}
    for claimed_contiguous in (False, True):
        missing_capture, gap_note = calculate_current_player_features(two_targets, pas, pitches,
            as_of_utc="2024-01-03T18:00:00Z",
            history_authority={**gap_source, "contiguousRequestedDatesComplete": claimed_contiguous}, annual_priors=priors)
        rolling = [field for field in missing_capture if feature_family(field) == "COMPLETED_PA_PITCH_HISTORY"]
        assert len(rolling) == 31 and missing_capture[rolling].isna().all().all()
        assert all(not row["windowSupported"] and not row["cumulativeExposureSupported"]
                   and not row["contiguousSourceCoverageVerified"] for row in gap_note["rows"])
        assert all(row["status"] == "INCOMPLETE_WINDOW_NOT_COLD_START" for row in gap_note["rows"])
        assert not gap_note["genericImputation"]
    with pytest.raises(ValueError, match="Target-date"):
        calculate_current_player_features(target, pas.assign(gameDate="2024-01-03"), pitches,
            as_of_utc="2024-01-03T18:00:00Z", history_authority=source)
    # Consumer-boundary fixture: only the source-loader's typed, date/receipt-bound
    # capability permits separately acquired operational history on protected dates.
    # No evaluation artifact, provider or predictive model is used in this test.
    from server.sports_current_statcast.mlb_v18_current_sources import (
        VerifiedOperationalHistory, OPERATIONAL_PURPOSE, OPERATIONAL_AUTHORIZATION,
    )
    operational_day, operational_cutoff = "2026-08-20", "2026-09-10T18:00:00Z"
    operational_source = {**source, "sourceIdentity": "ab"*32, "sourcePurpose": OPERATIONAL_PURPOSE,
        "observedAt": "2026-09-10T17:00:00Z", "availableAsOf": "2026-09-10T17:00:00Z",
        "ingestedAt": "2026-09-10T17:01:00Z", "completionConfirmedAt": "2026-09-10T17:00:00Z",
        "completeFrom": operational_day, "completeThrough": "2026-09-09",
        "requestedDates": [(date(2026, 8, 20)+timedelta(days=n)).isoformat() for n in range(21)]}
    op_pas, op_pitches = pas.copy(), pitches.copy()
    for frame in (op_pas, op_pitches):
        for key in ("sourceIdentity", "sourcePurpose", "observedAt", "availableAsOf", "ingestedAt", "completionConfirmedAt"):
            frame[key] = operational_source[key]
        frame["gameDate"] = operational_day
    op_pas["season"] = 2026
    op_target = target.assign(gameDate="2026-09-10")
    capability = VerifiedOperationalHistory(OPERATIONAL_PURPOSE, OPERATIONAL_AUTHORIZATION,
        ((operational_source["sourceIdentity"], operational_day),), operational_source["ingestedAt"])
    for invalid in (None, {"purpose": OPERATIONAL_PURPOSE},
                    VerifiedOperationalHistory("EVALUATION", OPERATIONAL_AUTHORIZATION, capability.receipt_days, capability.latest_ingested_at)):
        with pytest.raises(ValueError, match="authenticated NEW operational"):
            calculate_current_player_features(op_target, op_pas, op_pitches, as_of_utc=operational_cutoff,
                history_authority={**operational_source, "_operationalSourceCapability": invalid})
    op_authority = {**operational_source, "_operationalSourceCapability": capability}
    op_values, op_receipt = calculate_current_player_features(op_target, op_pas, op_pitches,
        as_of_utc=operational_cutoff, history_authority=op_authority)
    assert op_values.iloc[0].pitcher_last250_bf_count == 250
    assert op_values.iloc[0].pitcher_last250_fastball_velocity_sum == 93.125*250
    assert all(row["windowSupported"] for row in op_receipt["rows"])
    with pytest.raises(ValueError, match="verified new operational capture"):
        calculate_current_player_features(op_target, op_pas, op_pitches.assign(sourceIdentity="cd"*32),
            as_of_utc=operational_cutoff, history_authority=op_authority)
    with pytest.raises(ValueError, match="FINAL_OOT_SEALED"):
        calculate_current_player_features(op_target.assign(gameDate=operational_day), op_pas, op_pitches,
            as_of_utc=operational_cutoff, history_authority=op_authority)


def test_current_context_uses_accepted_orientation_and_contract_exact_246():
    from server.sports_current_statcast.mlb_v18_current_slate import load_contract, ROOT
    from server.sports_current_statcast.mlb_regime_baseline import verified_json
    source = {**_source(), "allSeasonScheduleComplete": True}
    kickoff = datetime(2024, 1, 3, 20, tzinfo=timezone.utc)
    game = GameContextInput("target", date(2024, 1, 3), "NYY", "BOS", "park", kickoff,
                            season_start_date=date(2024, 1, 1), series_game_number=3, games_in_series=3)
    priors = [GameContextInput(f"prior{i}", date(2024, 1, i), "NYY", "BOS", "park", kickoff-timedelta(days=3-i),
                             actual_end_utc=kickoff-timedelta(days=3-i)+timedelta(hours=3), innings_played=9) for i in (1, 2)]
    venues = {"park": VenueAuthority("park", 40.8296, -73.9262, "America/New_York", 55)}
    result, _ = calculate_current_context(game, history=[{**source, "game": p} for p in priors], venues=venues,
                                         as_of_utc="2024-01-03T18:00:00Z", history_authority=source)
    assert result["AWAY"] == build_team_game_context(game, "BOS", history=priors, venues=venues)
    assert result["HOME"] == build_team_game_context(game, "NYY", history=priors, venues=venues)
    contract = load_contract()
    metadata = verified_json(ROOT / ".runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/4171306af87bee46e74d2b5141189a5916382967322592243bf71e9eed9cf684.json")
    availability = {field: {"category": 2, "evidence": "SYNTHETIC_TEST_ONLY_NOT_ACTUAL_COVERAGE", "status": "FIXTURE", "repair": "NONE"}
                    for field in contract["rawFeatureColumns"]}
    reconciled = reconcile_field_contract(contract["rawFeatureColumns"], metadata, availability=availability)
    assert len(reconciled["fields"]) == 246
    assert reconciled["sourceFamilyCounts"]["ANNUAL_PLAYER_PRIOR"] == 25
    assert reconciled["sourceFamilyCounts"]["COMPLETED_PA_PITCH_HISTORY"] == 31
    assert reconciled["sourceFamilyCounts"]["TEAM_SCHEDULE_VENUE_CONTEXT"] == 150
    assert reconciled["categoryCounts"]["2"] == 246
    assert not set(reconciled["retiredOutsideSourceOrder"]) & set(reconciled["sourceOrder"])
    sides, roster, crosswalk = [], [], {}
    for side, team in (("HOME", "NYY"), ("AWAY", "BOS")):
        starter = "starter-"+side
        crosswalk[starter] = starter
        entries = []
        for n in range(1, 10):
            player = f"batter-{side}-{n}"
            crosswalk[player] = player
            entries.append({"mlbam": player, "batting_order": n, "bats": "L"})
        evidence = {"source": "SYNTHETIC_TEST", "observedAt": source["observedAt"], "availableAsOf": source["availableAsOf"]}
        sides.append({"side": side, "team": {"uuid": team, "abbreviation": team}, "lineup": entries,
            "lineupAuthority": {**evidence, "status": "CONFIRMED"},
            "starter": {**evidence, "mlbamId": starter, "throws": "R"}})
        player = "staff-"+side
        crosswalk[player] = player
        roster.append({**source, "mlbamId": player, "teamId": team, "role": "PITCHER", "activeRoster": True,
                       "rosterStatus": "ACTIVE", "throws": "R"})
    snapshot = {"capturedAt": "2024-01-03T18:00:00Z", "game": {"game_id": "target", "starts_at": kickoff.isoformat(),
        "source_venue_id": "3", "status": "SCHEDULED"}, "sides": sides, "currentRoster": roster,
        "gameState": [{"source": "SYNTHETIC_TEST", "observed_at": source["observedAt"], "available_as_of": source["availableAsOf"]}]}
    composed = compose_current_game(snapshot, {"pa_history": pd.DataFrame(), "pitches": pd.DataFrame(), "games": [],
        "authority": source, "mlbam_to_canonical": crosswalk}, contract)
    assert len(composed["rows"]) == 18 and all(list(row) == contract["rawFeatureColumns"] for row in composed["rows"])
    assert len(composed["providerInputs"]["awayBullpen"]) == len(composed["providerInputs"]["homeBullpen"]) == 1
    assert not any(b["reason"] == "CURRENT_BULLPEN_ROSTER_NOT_AVAILABLE" for b in composed["blockers"])
    assert not composed["canSimulate"]  # Missing history remains a real, explicit source dependency.
    snapshot["sides"][0]["lineup"][0]["bats"] = None
    supplement = {**source, "mlbamId": "batter-HOME-1", "canonicalPlayerId": "batter-HOME-1",
                  "bats": "R", "throws": "R", "sourcePurpose": "CURRENT_PLAYER_IDENTITY"}
    supplemented = compose_current_game(snapshot, {"pa_history": pd.DataFrame(), "pitches": pd.DataFrame(), "games": [],
        "authority": source, "mlbam_to_canonical": crosswalk, "currentPlayerIdentityEvidence": [supplement]}, contract)
    restored_row = next(row for row in supplemented["rows"] if row["batterCanonicalPlayerId"] == "batter-HOME-1")
    assert restored_row["matchup_batter_hand_missing"] == 0
    assert restored_row["matchup_batter_bats_left"] == restored_row["matchup_batter_bats_switch"] == 0
    assert snapshot["sides"][0]["lineup"][0]["bats"] is None  # Original capture never overwritten.
    assert supplemented["sourceEvidence"]["currentPlayerIdentitySupplements"] == [supplement]
