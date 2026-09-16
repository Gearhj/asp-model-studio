from __future__ import annotations

import asyncio

from server.sports_shared.independent_source_steps import SourceStep, run_independent_source_steps


class ConnectTimeout(Exception):
    pass


def test_team_stats_timeout_does_not_skip_roster_or_bullpen():
    called: list[str] = []

    async def fail_stats():
        called.append("TEAM_STATS")
        raise ConnectTimeout("retained ConnectTimeout sequence")

    async def succeed(name: str):
        called.append(name)
        return {"fresh": True}

    result = asyncio.run(run_independent_source_steps([
        SourceStep("TEAM_STATS", fail_stats),
        SourceStep("ACTIVE_ROSTER", lambda: succeed("ACTIVE_ROSTER")),
        SourceStep("BULLPEN_WORKLOAD", lambda: succeed("BULLPEN_WORKLOAD")),
    ], expected_error=ConnectTimeout))

    assert called == ["TEAM_STATS", "ACTIVE_ROSTER", "BULLPEN_WORKLOAD"]
    assert [item["status"] for item in result["attempts"]] == ["FAILED", "COMPLETED", "COMPLETED"]
    assert [item["attemptCount"] for item in result["attempts"]] == [1, 1, 1]
    assert result["automaticRetriesAdded"] == 0
    assert result["staleEvidenceSubstituted"] is False
    assert result["values"]["ACTIVE_ROSTER"] == {"fresh": True}
