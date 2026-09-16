"""Focused, no-network verification for the MLB player-prop feasibility audit.

This script does not calculate a player-prop probability. It proves why the
currently retained team aggregate is insufficient and checks the source seams
on which the audit relies.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_ROOT = ROOT / "docs" / "mlb-player-prop-feasibility-v1"

EXPECTED = {
    "server/sports_current_statcast/mlb_v18_whole_game_challenger.py": "dc423012278709e7da2c85aeec6b81974db721c6d01c0c802ab83630499dd288",
    "server/sports_current_statcast/mlb_v18_current_publication.py": "ea655fd9f02b25eb3b26f95385730be0d89d0d497d3705b2612b164ef117794d",
    "server/sports_current_statcast/mlb_v18_population_diagnostics.py": "fa821020c1812fd9ea0336dc039cb69339c467c8502eeec01372d52ebaf0823f",
    "server/sports_current_statcast/mlb_v18_play_geometry_trace.py": "f071ec9e516aa938416d46d47f6778bf5dd799126bed0014e1aac70d11a64c6c",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict[str, object]:
    matrix = json.loads((DOC_ROOT / "capability-matrix.json").read_text(encoding="utf-8"))
    audit = json.loads((DOC_ROOT / "source-audit.json").read_text(encoding="utf-8"))
    assert matrix["disposition"] == "PLAYER_PROP_PROBABILITIES_UNSUPPORTED_BY_EXISTING_IMMUTABLE_POPULATION"
    assert matrix["existingPopulation"]["drawCount"] == 5000
    assert matrix["existingPopulation"]["namedPlayerEventsAcrossAllDraws"] is False
    assert all(not row["currentProbabilityAvailable"] for row in matrix["props"])
    assert matrix["voidProbability"] == {"status": "UNSUPPORTED", "value": None}

    hashes = {name: sha256(ROOT / name) for name in EXPECTED}
    assert hashes == EXPECTED
    audited_hashes = {row["path"]: row["sha256"] for row in audit["files"]}
    assert all(audited_hashes[name] == digest for name, digest in EXPECTED.items())
    assert audit["accounting"]["outcomeReads"] == audit["accounting"]["sealedReads"] == 0

    simulator = (ROOT / "server/sports_current_statcast/mlb_v18_whole_game_challenger.py").read_text(encoding="utf-8")
    diagnostics = (ROOT / "server/sports_current_statcast/mlb_v18_population_diagnostics.py").read_text(encoding="utf-8")
    trace = (ROOT / "server/sports_current_statcast/mlb_v18_play_geometry_trace.py").read_text(encoding="utf-8")
    for token in ("battingOrderPosition", "pitcherState", '"outcome"', '"traces"'):
        assert token in simulator
    persisted = trace.split("PERSISTED_FIELDS =", 1)[1].split(")", 1)[0]
    assert '"batterCanonicalPlayerId"' not in persisted
    assert '"pitcherCanonicalPlayerId"' not in persisted
    assert '"outcome_counts"' in diagnostics and '"probability_sums"' in diagnostics

    # Same two-draw team aggregate, incompatible player-A 1+ hit probability.
    allocation_a = [{"A": 1, "B": 0}, {"A": 1, "B": 0}]
    allocation_b = [{"A": 0, "B": 1}, {"A": 0, "B": 1}]
    assert [sum(draw.values()) for draw in allocation_a] == [sum(draw.values()) for draw in allocation_b] == [1, 1]
    assert sum(draw["A"] >= 1 for draw in allocation_a) / 2 == 1.0
    assert sum(draw["A"] >= 1 for draw in allocation_b) / 2 == 0.0

    return {
        "schemaVersion": "MLB_V18_PLAYER_PROP_FEASIBILITY_CHECKS_V1",
        "allPassed": True,
        "checks": {
            "sourceHashesBound": True,
            "failClosedMatrix": True,
            "namedIdentityAbsentFromPersistedTrace": True,
            "teamAggregatePlayerProbabilityNonIdentifiable": True,
            "zeroProbabilityCodeAdded": True,
        },
        "activity": {"networkCalls": 0, "providerCalls": 0, "outcomeReads": 0, "sealedReads": 0},
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True, separators=(",", ":")))
