from scripts.verify_mlb_player_prop_feasibility_v1 import verify


def test_focused_feasibility_audit() -> None:
    result = verify()
    assert result["allPassed"] is True
    assert all(result["checks"].values())
    assert result["activity"] == {
        "networkCalls": 0,
        "providerCalls": 0,
        "outcomeReads": 0,
        "sealedReads": 0,
    }
