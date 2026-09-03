from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.persistence import persistence_router
from server.sports_current_statcast.stage3_game_scoring import (
    Stage3GameScoringError,
)


def test_executable_artifact_and_game_scoring_routes_require_authentication() -> None:
    expected = (
        ("GET", "/projects/{project_id}/sports/stage3-executable-artifact"),
        ("POST", "/projects/{project_id}/sports/stage3-executable-artifact/plan"),
        ("GET", "/projects/{project_id}/sports/stage3-executable-artifact/jobs"),
        ("POST", "/projects/{project_id}/sports/stage3-executable-artifact/jobs"),
        (
            "GET",
            "/projects/{project_id}/sports/stage3-executable-artifact/jobs/{job_id}",
        ),
        (
            "POST",
            "/projects/{project_id}/sports/stage3-executable-artifact/jobs/{job_id}/cancel-unstarted",
        ),
        ("GET", "/projects/{project_id}/sports/stage3-game-scoring"),
        ("POST", "/projects/{project_id}/sports/stage3-game-scoring/jobs"),
        (
            "GET",
            "/projects/{project_id}/sports/stage3-game-scoring/jobs/{job_id}",
        ),
    )
    for method, path in expected:
        matches = [
            route
            for route in persistence_router.router.routes
            if route.path == path and method in route.methods
        ]
        assert len(matches) == 1
        assert any(
            dependency.call is persistence_router.require_user
            for dependency in matches[0].dependant.dependencies
        )


def test_game_scoring_blocker_retains_exact_http_status_and_detail() -> None:
    failure = Stage3GameScoringError(
        "GOVERNED_PREGAME_LINEUP_STARTER_AUTHORITY_UNAVAILABLE",
        "No governed pregame authority is available.",
        status_code=409,
    )

    with pytest.raises(HTTPException) as captured:
        persistence_router._run_stage3_prepare(lambda: (_ for _ in ()).throw(failure))

    assert captured.value.status_code == 409
    assert captured.value.detail == {
        "code": "GOVERNED_PREGAME_LINEUP_STARTER_AUTHORITY_UNAVAILABLE",
        "message": "No governed pregame authority is available.",
    }
