"""Identity-only protection; no outcome/forecast/source payload is read."""
import pytest

from server.sports_current_statcast.mlb_starter_duration_quarantine import (
    ALLOWED, LEDGER, assert_prospective_source_allowed, final_oot_eligible_key_mask,
    load_exception_authority, reference, require_reduced_final_oot_report,
)


def test_three_game_source_exception_never_grants_evaluation_or_other_games():
    authority = load_exception_authority()
    assert authority["evaluationAllowed"] is False
    for pitcher, game, day in ALLOWED:
        assert assert_prospective_source_allowed(pitcher, game, day)["authorityRef"] == authority["authorityRef"]
    with pytest.raises(ValueError, match="OUTSIDE_THREE_GAME"):
        assert_prospective_source_allowed("664285", 823344, "2026-08-18")
    with pytest.raises(ValueError, match="OUTSIDE_THREE_GAME"):
        assert_prospective_source_allowed("690279", 823343, "2026-08-17")
    denied = [g["canonicalGameId"] for g in authority["quarantine"]["games"]]
    assert final_oot_eligible_key_mask(denied + ["mlbam:game:823343", 824235, "synthetic-uncontaminated-key"]) == [False] * 5 + [True]
    disclosure = {"quarantineRef": reference(LEDGER), "originalUntouchedFinalOot": False,
                  "cohortStatus": "REDUCED_FINAL_OOT_AFTER_PROSPECTIVE_FEATURE_CONSTRUCTION"}
    with pytest.raises(ValueError, match="QUARANTINED_GAME"):
        require_reduced_final_oot_report(denied, disclosure)
    with pytest.raises(ValueError, match="DISCLOSURE_REQUIRED"):
        require_reduced_final_oot_report(["synthetic-uncontaminated-key"], {})
    require_reduced_final_oot_report(["synthetic-uncontaminated-key"], disclosure)
