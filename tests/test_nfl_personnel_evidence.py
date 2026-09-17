from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from server.sports_nfl_m1.personnel_capture import build_capture_plan, execute_capture
from server.sports_nfl_m1.personnel_evidence import (
    Admissibility,
    EvidenceError,
    Missingness,
    PregamePersonnelRecord,
    PriorQuarterbackObservation,
    PriorRoleObservation,
    append_revision,
    injury_burden_counts,
    normalize_injury_status,
    prior_role_features,
    quarterback_cold_start,
    quarterback_prior_features,
    resolve_canonical_player,
)


def record(**changes) -> PregamePersonnelRecord:
    values = dict(
        canonical_game_id="2026_02_AAA_BBB", canonical_player_id="00-0000001",
        canonical_team_id="BBB", source_id="nflverse-injuries",
        source_asset_id="injuries_2026.parquet", source_release_id="injuries",
        source_publication_time_utc="2026-09-12T16:00:00Z",
        retrieval_time_utc="2026-09-12T16:05:00Z", effective_time_utc="2026-09-12T16:00:00Z",
        scheduled_kickoff_utc="2026-09-13T17:00:00Z", feature_cutoff_utc="2026-09-13T16:30:00Z",
        practice_status="LIMITED", game_status="QUESTIONABLE", roster_status="ACTIVE",
        expected_role="STARTER", position_group="QB", expected_availability="UNCERTAIN", confirmed_inactive=None,
        actual_participation=None, revision=1, predecessor_sha256=None,
        source_row_sha256="a" * 64, admissibility=Admissibility.PROSPECTIVE_ONLY,
    )
    values.update(changes)
    return PregamePersonnelRecord(**values)


def test_cutoff_and_target_participation_fail_closed() -> None:
    record().validate()
    with pytest.raises(EvidenceError, match="captured prospective evidence"):
        record(source_publication_time_utc="2026-09-13T16:45:00Z",
               retrieval_time_utc="2026-09-13T16:50:00Z").validate()
    with pytest.raises(EvidenceError, match="participation"):
        record(actual_participation=True).validate()
    with pytest.raises(EvidenceError, match="cutoff"):
        record(feature_cutoff_utc="2026-09-13T17:01:00Z").validate()
    with pytest.raises(EvidenceError, match="pre-cutoff retrieval"):
        record(retrieval_time_utc="2026-09-13T16:45:00Z").validate()


def test_historical_admissibility_requires_proven_publication() -> None:
    with pytest.raises(EvidenceError, match="historical point-in-time"):
        record(admissibility=Admissibility.HISTORICALLY_POINT_IN_TIME_ADMISSIBLE,
               source_publication_time_utc=None).validate()


def test_revision_chain_is_append_only_and_deterministic() -> None:
    first = record()
    chain = append_revision((), first)
    second = replace(first, revision=2, predecessor_sha256=first.digest(), game_status="OUT",
                     source_publication_time_utc="2026-09-12T20:00:00Z",
                     retrieval_time_utc="2026-09-12T20:05:00Z")
    assert append_revision(chain, second)[-1].digest() == second.digest()
    with pytest.raises(EvidenceError, match="predecessor"):
        append_revision(chain, replace(second, predecessor_sha256="0" * 64))


def test_player_identity_uses_ids_and_fails_on_ambiguity() -> None:
    identities = [
        {"canonical_player_id": "P1", "gsis_id": "G1", "display_name": "Same Name"},
        {"canonical_player_id": "P2", "gsis_id": "G2", "display_name": "Same Name"},
    ]
    assert resolve_canonical_player({"gsis_id": "G1"}, identities) == "P1"
    with pytest.raises(EvidenceError):
        resolve_canonical_player({"display_name": "Same Name"}, identities)
    with pytest.raises(EvidenceError):
        resolve_canonical_player({"gsis_id": None}, identities)


def test_injury_vocabulary_preserves_non_deterministic_states() -> None:
    assert normalize_injury_status("Questionable", kind="game") == "QUESTIONABLE"
    assert normalize_injury_status("Limited Participation in Practice", kind="practice") == "LIMITED"
    assert normalize_injury_status(None, kind="game") == "NO_DESIGNATION"
    burden = injury_burden_counts([record()], feature_cutoff_utc=record().feature_cutoff_utc)
    assert burden["listedPlayerCount"] == 1
    assert burden["availabilityWeightsApplied"] is False


def test_cold_start_does_not_treat_missing_draft_as_undrafted() -> None:
    result = quarterback_cold_start(expected_player_id="P1", prior_starts=0,
                                    current_season_starts=0, rookie_season=2026,
                                    target_season=2026, draft_record_present=False,
                                    undrafted_explicit=None)
    assert result["firstNflStart"] is True
    assert result["draftState"] == "DRAFT_STATUS_UNKNOWN"
    unresolved = quarterback_cold_start(expected_player_id=None, prior_starts=None,
                                        current_season_starts=None, rookie_season=None,
                                        target_season=2026, draft_record_present=False,
                                        undrafted_explicit=None)
    assert unresolved["missingness"] == Missingness.PLAYER_IDENTITY_UNRESOLVED.value


def test_qb_performance_is_strictly_prior_and_target_game_rejected() -> None:
    prior = PriorQuarterbackObservation("G0", "P1", 2025, "2026-09-01T00:00:00Z", True, 20, 2.0, 10, 2, 1)
    future = PriorQuarterbackObservation("G2", "P1", 2026, "2026-09-14T00:00:00Z", True, 30, 9.0, 20, 1, 0)
    result = quarterback_prior_features(expected_player_id="P1", target_game_id="G1", target_season=2026,
                                        cutoff_utc="2026-09-13T00:00:00Z", observations=[prior, future])
    assert result["attempts"] == 20
    assert result["sourceGameIds"] == ["G0"]
    target = replace(prior, canonical_game_id="G1")
    with pytest.raises(EvidenceError, match="target-game"):
        quarterback_prior_features(expected_player_id="P1", target_game_id="G1", target_season=2026,
                                   cutoff_utc="2026-09-13T00:00:00Z", observations=[target])


def test_target_game_snaps_are_rejected() -> None:
    prior = PriorRoleObservation("G0", "P1", "AAA", "2026-09-01T00:00:00Z", 50, 0, 2)
    assert prior_role_features(canonical_player_id="P1", canonical_team_id="AAA", target_game_id="G1",
                               cutoff_utc="2026-09-13T00:00:00Z", observations=[prior])["meanOffenseSnaps"] == 50
    with pytest.raises(EvidenceError, match="target-game snap"):
        prior_role_features(canonical_player_id="P1", canonical_team_id="AAA", target_game_id="G1",
                            cutoff_utc="2026-09-13T00:00:00Z",
                            observations=[replace(prior, canonical_game_id="G1")])


def test_capture_is_dry_by_default_and_synthetic_execution_is_idempotent(tmp_path: Path) -> None:
    plan = build_capture_plan(2026)
    assert len(plan.assets) == 7
    assert plan.content()["defaultMode"] == "DRY_RUN_NO_NETWORK"
    with pytest.raises(PermissionError):
        execute_capture(plan, output_root=tmp_path)

    calls = []
    def fetch(asset, conditional, maximum_bytes):
        calls.append(asset.asset_name)
        assert maximum_bytes > 0
        if conditional:
            return None, {"ETag": "fixture"}
        return (f"synthetic:{asset.asset_name}".encode(), {"ETag": "fixture", "Ignored": "x"})

    one = execute_capture(plan, output_root=tmp_path, allow_network=True, rights_approved=True,
                          fetcher=fetch, captured_at_utc="2026-09-10T12:00:00Z")
    two = execute_capture(plan, output_root=tmp_path, allow_network=True, rights_approved=True,
                          fetcher=fetch, captured_at_utc="2026-09-10T12:00:00Z")
    assert one["receiptSha256"] != two["receiptSha256"]  # retention disposition is audited
    assert one["newObjects"] == 7 and two["newObjects"] == 0
    assert one["responseBytes"] > 0 and two["responseBytes"] == 0
    assert len(calls) == 14
