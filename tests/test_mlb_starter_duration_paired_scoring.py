from datetime import datetime, timezone

import numpy as np
import pytest

from server.sports_current_statcast.mlb_starter_duration_paired_scoring import (
    eligible_final_queries, empirical_crps, joint_energy_score, score_pair,
    FINAL_METADATA_QUERY, FINAL_QUERY, STARTER_FINAL_QUERY, read_persisted_finals,
    _starter_final_evidence,
)


def test_exact_distribution_scores_pair_identity_corrections_and_outcome_read_guard():
    pair = {"gameId": "pilot-game", "commonPairId": "frozen-pair", "scheduledStartUtc": "2026-09-11T00:01:00Z"}
    final = {"gameId": "pilot-game", "status": "FINAL", "homeScore": 3, "awayScore": 1,
             "finalAt": "2026-09-11T01:00:00Z", "sourceRevision": 1, "retrievedAt": "2026-09-11T02:00:00Z"}
    pop = {"reference": {"homeRuns": np.array([2, 4, 4, 2]), "awayRuns": np.array([1, 1, 1, 1])},
           "challenger": {"homeRuns": np.array([3, 3, 3, 3]), "awayRuns": np.array([1, 1, 1, 1])}}
    result = score_pair(pair, pop, final)
    assert result["accounting"]["matchedGames"] == 1
    assert result["arms"]["reference"]["marginals"]["homeRuns"]["crps"] == 0.5
    assert result["arms"]["challenger"]["jointEuclideanEnergyScore"] == 0
    assert result["challengerMinusReference"]["jointEuclideanEnergyScore"] == -0.5
    assert result["pairedMonteCarlo"]["homeRuns"]["challengerMinusReference"] == 0
    assert result["pairedMonteCarlo"]["homeRuns"]["pairedMonteCarloStandardError"] == pytest.approx(np.sqrt(1/3))
    assert result["arms"]["reference"]["homeWinProbability"] == 1
    assert result["arms"]["reference"]["winnerBrier"] == 0
    assert np.isfinite(result["arms"]["reference"]["winnerLogLoss"])
    assert result["scoreIdentity"] == score_pair(pair, pop, {**final, "retrievedAt": "later"})["scoreIdentity"]
    assert result["scoreIdentity"] != score_pair(pair, pop, {**final, "sourceRevision": 2})["scoreIdentity"]
    assert result["scoreIdentity"] != score_pair(pair, pop, {**final,
        "homeStarterBf": 22, "starterEvidence": {"sha256": "corrected-starter-source"}})["scoreIdentity"]
    assert result["scoreIdentity"] != score_pair(pair, {**pop, "challenger": {
        "homeRuns": [4, 4, 4, 4], "awayRuns": [1, 1, 1, 1]}}, final)["scoreIdentity"]
    assert result["definitions"]["acrossGameConfidenceInterval"] is None
    assert result["arms"]["reference"]["starterDuration"] == {}
    x = np.array([0., 1., 4., 9.])
    assert empirical_crps(x, 2) == pytest.approx(np.abs(x-2).mean()-np.abs(x[:, None]-x).mean()/2)
    joint = np.array([[0., 1.], [2., 4.], [5., 1.]])
    expected = np.linalg.norm(joint-[1, 2], axis=1).mean()-np.linalg.norm(joint[:, None]-joint, axis=2).mean()/2
    assert joint_energy_score(joint[:, 0], joint[:, 1], (1, 2)) == pytest.approx(expected)
    with pytest.raises(ValueError, match="identity"):
        score_pair(pair, pop, {**final, "gameId": "other"})
    with pytest.raises(ValueError, match="FINAL"):
        score_pair(pair, pop, {**final, "status": "LIVE"})
    with pytest.raises(ValueError, match="Tied"):
        score_pair(pair, pop, {**final, "awayScore": 3})
    with pytest.raises(ValueError, match="actual current time"):
        score_pair(pair, pop, {**final, "finalAt": "2099-09-11T01:00:00Z"})
    queries, withheld = eligible_final_queries([pair, pair,
        {**pair, "gameId": "old", "commonPairId": "old", "scheduledStartUtc": "2026-08-20T12:00:00Z"},
        {**pair, "gameId": "future", "commonPairId": "future", "scheduledStartUtc": "2026-09-12T12:00:00Z"}],
        now=datetime(2026, 9, 11, 18, tzinfo=timezone.utc))
    assert [x["gameId"] for x in queries] == ["pilot-game"]
    assert {x["reason"] for x in withheld} == {"OUTSIDE_PROSPECTIVE_PILOT", "NOT_STARTED"}


def test_status_metadata_prevents_any_nonfinal_score_query(monkeypatch):
    """Synthetic database transport only; no connection or outcome values read."""
    import sqlalchemy

    pair = {"gameId": "pilot-game", "commonPairId": "frozen-pair", "scheduledStartUtc": "2026-09-11T00:01:00Z"}
    metadata = {"game_id": "pilot-game", "starts_at": pair["scheduledStartUtc"], "game_status": "LIVE",
                "game_final_at": None, "outcome_id": None, "outcome_status": None, "revision": None,
                "outcome_created_at": None, "outcome_final_at": None}
    queries = []
    allow_final = False
    savepoint_events = []

    class Result:
        def __init__(self, value=None):
            self.value = value
        def scalar(self):
            return "on"
        def mappings(self):
            return self
        def one_or_none(self):
            return dict(metadata) if self.value is None else dict(self.value)

    class Transaction:
        def rollback(self):
            pass

    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def begin(self):
            return Transaction()
        def begin_nested(self):
            savepoint_events.append("begin")
            class Savepoint:
                def rollback(self):
                    savepoint_events.append("rollback")
                def commit(self):
                    savepoint_events.append("commit")
            return Savepoint()
        def exec_driver_sql(self, sql):
            return Result()
        def execute(self, sql, params):
            query = str(sql)
            queries.append(query)
            if allow_final and query == FINAL_QUERY:
                return Result({**metadata, "outcome_home_score": 3, "outcome_away_score": 1})
            if allow_final and query == STARTER_FINAL_QUERY:
                raise RuntimeError("Synthetic optional table unavailable")
            assert query == FINAL_METADATA_QUERY
            assert "home_score" not in query and "away_score" not in query
            return Result()

    class Engine:
        def connect(self):
            return Connection()
        def dispose(self):
            pass

    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: Engine())
    for updates, reason in (({}, "PERSISTED_FINAL_NOT_AVAILABLE"),
                            ({"game_status": "FINAL"}, "PROVENANCE_BEARING_FINAL_REQUIRED"),
                            ({"game_status": "FINAL", "game_final_at": "2026-09-11T01:00:00Z", "outcome_id": "revised", "outcome_status": "VOIDED"},
                             "PERSISTED_FINAL_NOT_AVAILABLE")):
        metadata.update(updates)
        result = read_persisted_finals([pair], database_url="postgresql://fixture@127.0.0.1/fixture")
        assert result["source"]["metadataQueriesExecuted"] == 1
        assert result["source"]["finalScoreQueriesExecuted"] == 0
        assert result["records"][0]["reason"] == reason
        assert result["records"][0]["outcomeValuesRead"] is False
    assert len(queries) == 3
    # SQL repeats the final gates so a reversion between metadata and value reads
    # cannot cause a nonfinal score projection.
    assert "upper(o.outcome_status::text)='FINAL'" in FINAL_QUERY
    assert "o.id is null and upper(g.status::text)='FINAL'" not in FINAL_QUERY
    assert "g.home_score" not in FINAL_QUERY and "g.away_score" not in FINAL_QUERY
    assert "o.final_at <= :query_started_at" in FINAL_QUERY
    # A failure in the optional BF interface is isolated behind a savepoint and
    # leaves the admitted final score available for whole-game metrics.
    from server.sports_current_statcast import mlb_starter_duration_paired_scoring as scoring
    monkeypatch.setattr(scoring, "_expected_starters", lambda pair: {"sides": {
        "HOME": {"playerId": "p"}, "AWAY": {"playerId": "q"}}})
    metadata.update(outcome_status="FINAL", revision=2, outcome_created_at="2026-09-11T01:01:00Z",
                    outcome_final_at="2026-09-11T01:00:00Z")
    allow_final = True
    admitted = read_persisted_finals([pair], database_url="postgresql://fixture@127.0.0.1/fixture")
    assert admitted["records"][0]["status"] == "FINAL" and admitted["records"][0]["homeScore"] == 3
    assert admitted["records"][0]["starterEvidence"]["status"] == "ACTUAL_STARTER_BF_UNAVAILABLE"
    assert admitted["source"]["optionalStarterQueriesExecuted"] == 1
    assert savepoint_events == ["begin", "rollback"]

    # Synthetic starter-source projection: exact final/source identities are
    # required, and conflicting latest sources never resolve by arbitrary pick.
    expected = {"inputReference": {"sha256": "synthetic-input"}, "sides": {
        "HOME": {"playerId": "p", "teamId": "t", "mlbamId": "664285", "sourceTeamId": "116", "sourceGameId": "824227"}}}
    final = {"gameId": "g", "sourceOutcomeId": "f", "sourceRevision": 2, "scheduledStartUtc": "2026-09-11T00:01:00Z"}
    row = {"observation_id": "ob", "game_id": "g", "player_id": "p", "team_id": "t", "final_outcome_id": "f",
           "source_record_id": "824227:664285:116:PITCHER", "role": "PITCHER", "started": True,
           "actual_starting_pitcher": True, "starter_provenance": "ACTUAL_STARTER_HISTORICAL_RECONSTRUCTION",
           "source_mode": "LIVE", "source_version_mode": "LIVE", "source_classification": "OFFICIAL_PRIMARY",
           "evaluation_eligible": True, "source_quality_tier": "VERIFIED_HISTORICAL", "checkpoint_status": "SUCCEEDED",
           "checkpoint_source_mode": "LIVE", "checkpoint_temporal_semantics": "RETROSPECTIVE_RECONSTRUCTION",
           "checkpoint_source_version_id": "v", "source_version_id": "v", "raw_references": ["synthetic-raw"],
           "raw_checksums": ["0"*64], "actual_bf": "22", "actual_outs": "15", "actual_innings": "5.0"}
    for key in ("payload_checksum", "identity_checksum", "checkpoint_identity_checksum", "source_identity_checksum"):
        row[key] = "0"*64
    for key in ("checkpoint_requested_at", "checkpoint_completed_at", "created_at", "retrieved_at", "evidence_end_at"):
        row[key] = "2026-09-11T03:00:00Z"
    now = datetime(2026, 9, 11, 18, tzinfo=timezone.utc)
    actual = _starter_final_evidence([row], expected, final, queried_at=now)
    assert actual["sides"]["HOME"]["actualBf"] == 22 and actual["sides"]["HOME"]["actualOuts"] == 15
    assert actual["rawSourceBytesIndependentlyRehashed"] is False
    conflict = _starter_final_evidence([row, {**row, "actual_bf": "23"}], expected, final, queried_at=now)
    assert conflict["sides"]["HOME"]["reason"] == "AMBIGUOUS_ACTUAL_STARTER_EVIDENCE"
    changed_final = _starter_final_evidence([{**row, "final_outcome_id": "older"}], expected, final, queried_at=now)
    assert changed_final["sides"]["HOME"]["status"] == "UNSUPPORTED"
    absent = _starter_final_evidence([], expected, final, queried_at=now)
    assert absent["sides"]["HOME"]["reason"] == "PERSISTED_ACTUAL_STARTER_HISTORY_NOT_AVAILABLE"
