import pandas as pd
import pytest

from server.sports_current_statcast.mlb_v18_development_timing import (
    project_contributions, training_prefix_mask, contribution_day_blocks, interdate_reorder_impact,
)


def fixture():
    rows = pd.DataFrame({"canonicalPaId": ["pa1", "pa2", "pa3", "pa4"],
                         "canonicalGameId": ["BOS", "MID", "NYN", "UNKNOWN26"],
                         "game_date": ["2024-06-26", "2024-07-10", "2023-09-28", "2026-06-16"],
                         "batterCanonicalPlayerId": ["b1"] * 4})
    authority = pd.DataFrame({"canonicalGameId": rows.canonicalGameId,
        "eventDate": rows.game_date, "completionDate": ["2024-08-26", "2024-07-10", None, None],
        "timingStatus": ["RECONSTRUCTED_DATE", "RECONSTRUCTED_DATE", "REVERTED_UNKNOWN", "UNCERTIFIED_2026"],
        "observedPublicationAt": [None] * 4})
    return rows, authority


def test_completion_prefix_and_unknown_never_substitute_original_date():
    rows, authority = fixture()
    projected = project_contributions(rows, authority)
    assert training_prefix_mask(projected, "2024-07-07", allow_reconstructed_date=True).tolist() == [False] * 4
    assert training_prefix_mask(projected, "2024-08-26", allow_reconstructed_date=True).tolist() == [False, True, False, False]
    assert training_prefix_mask(projected, "2024-08-27", allow_reconstructed_date=True).tolist() == [True, True, False, False]
    assert not training_prefix_mask(projected, "2027-01-01").any()
    assert projected.game_date.tolist() == rows.game_date.tolist()


def test_rolling_partial_order_changes_and_same_day_not_invented():
    rows, authority = fixture()
    projected = project_contributions(rows, authority)
    blocks = contribution_day_blocks(projected, "batterCanonicalPlayerId", "2024-08-27")
    assert blocks.canonicalGameId.tolist() == ["MID", "BOS"]
    impact = interdate_reorder_impact(projected, "batterCanonicalPlayerId")
    assert impact["paRowsInReversedBlocks"] == 2 and impact["reversedBlockPairs"] == 1
    authority.loc[authority.canonicalGameId.eq("MID"), "completionDate"] = "2024-08-26"
    projected = project_contributions(rows, authority)
    blocks = contribution_day_blocks(projected, "batterCanonicalPlayerId", "2024-08-27")
    assert blocks.withinDayOrderUnknown.all() and blocks.completionDayRank.nunique() == 1


def test_date_identity_and_protected_boundary_fail_before_projection():
    rows, authority = fixture()
    rows.loc[0, "game_date"] = "2026-08-14"
    with pytest.raises(ValueError, match="Development"):
        project_contributions(rows, authority)
    rows, authority = fixture()
    authority.loc[0, "eventDate"] = "2024-06-25"
    with pytest.raises(ValueError, match="original event"):
        project_contributions(rows, authority)
