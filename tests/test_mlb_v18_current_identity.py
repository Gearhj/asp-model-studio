"""Request scope only: synthetic accepted identity mapping, with HTTP forbidden."""
import pytest

from server.sports_current_statcast import mlb_v18_current_identity as identity
from server.sports_current_statcast import pipeline
from server.sports_current_statcast import mlb_v18_current_sources as sources


def test_identity_request_requires_explicit_current_scope_and_accepted_mapping(monkeypatch):
    monkeypatch.setattr(pipeline, "_load_player_identity", lambda path: (
        {"683011": "SYNTHETIC_LEGACY_VOLPE", "123456": "SYNTHETIC_CURRENT_PLAYER"}, {"synthetic": True}))
    def forbidden_http(*args, **kwargs):
        raise AssertionError("Scope-only tests must not make HTTP requests")
    monkeypatch.setattr(identity, "urlopen", forbidden_http)
    monkeypatch.setattr(sources, "urlopen", forbidden_http)
    assert identity.acquire_current_identity("683011")["status"] == "FREE_SOURCE_REQUEST_NOT_EXECUTED"
    with pytest.raises(identity.CurrentSourceError, match="outside the explicit current pregame"):
        identity.acquire_current_identity("123456")
    with pytest.raises(identity.CurrentSourceError, match="outside the explicit current pregame"):
        identity.acquire_current_identity("123456", eligible_current_ids=["123457"])
    planned = identity.acquire_current_identity("123456", eligible_current_ids=["123456"])
    assert planned["status"] == "FREE_SOURCE_REQUEST_NOT_EXECUTED"
    assert planned["mlbamId"] == "123456"
    assert "personIds=123456" in planned["url"]
    with pytest.raises(identity.CurrentSourceError, match="accepted canonical identity crosswalk"):
        identity.acquire_current_identity("999999", eligible_current_ids=["999999"])
