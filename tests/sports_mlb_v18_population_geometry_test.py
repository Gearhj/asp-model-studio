from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pytest

from server.sports_current_statcast.mlb_v18_population_geometry import (
    ACCEPTANCE_PROTOCOL_V2_SHA256,
    EXPECTED_SIMULATIONS,
    PLAY_GEOMETRY_SHA256,
    PARENT_BUNDLE_SHA256,
    PopulationGeometryError,
    accumulation_frames,
    load_or_broadcast,
    representative_indices,
    verify_manifest,
)


OUTPUT = Path("outputs/mlb-v18-population-geometry")


def _result() -> dict:
    away = np.resize(np.array([1, 4, 2, 8, 3]), EXPECTED_SIMULATIONS)
    home = np.resize(np.array([2, 1, 3, 4, 3]), EXPECTED_SIMULATIONS)
    # Eliminate ties because the production simulator always completes a game.
    home[home == away] += 1
    return {
        "simulationCount": EXPECTED_SIMULATIONS,
        "awayRuns": away,
        "homeRuns": home,
        "innings": np.resize(np.array([9, 9, 10, 9, 9]), EXPECTED_SIMULATIONS),
        "paCounts": np.full(EXPECTED_SIMULATIONS, 70),
    }


def test_frames_are_monotone_deterministic_and_end_at_5000() -> None:
    result = _result()
    counts = {
        "contact": np.ones(EXPECTED_SIMULATIONS, dtype=int),
        "scoring": np.ones(EXPECTED_SIMULATIONS, dtype=int) * 2,
        "geometry": np.ones(EXPECTED_SIMULATIONS, dtype=int),
        "runnerSegments": np.ones(EXPECTED_SIMULATIONS, dtype=int) * 3,
    }
    first = accumulation_frames(result, counts)
    second = accumulation_frames(result, counts)
    assert first == second
    assert len(first) == 100
    assert [row["cumulativeSimulationCount"] for row in first] == list(range(50, 5001, 50))
    assert first[-1]["cumulativeSimulationCount"] == 5000
    assert first[-1]["cumulativeContactPlayCount"] == 5000
    assert first[-1]["cumulativeRunnerPathTraffic"] == 15000
    assert len({row["frameDigest"] for row in first}) == 100


def test_representative_selectors_are_deterministic_and_genuine() -> None:
    result = _result()
    forecast = {"meanTotalRuns": 6.0, "meanRunDifferential": -0.5}
    first = representative_indices(result, forecast)
    assert first == representative_indices(result, forecast)
    assert set(first) == {"TYPICAL", "HOME_WIN", "AWAY_WIN", "HIGH_SCORING", "LOW_SCORING", "EXTRA_INNINGS"}
    for name, row in first.items():
        index = row["simulationIndex"]
        if name == "HOME_WIN":
            assert result["homeRuns"][index] > result["awayRuns"][index]
        if name == "AWAY_WIN":
            assert result["awayRuns"][index] > result["homeRuns"][index]
        if name == "EXTRA_INNINGS":
            assert result["innings"][index] > 9


def _published() -> Path:
    if not (OUTPUT / "latest.json").is_file():
        pytest.skip("population supplement has not been generated")
    latest = json.loads((OUTPUT / "latest.json").read_text(encoding="utf-8"))
    return Path(latest["relativePath"])


def test_published_population_reconciles_every_required_count() -> None:
    root = _published()
    manifest = verify_manifest(root)
    summary = json.loads((root / "population-summary.json").read_text(encoding="utf-8"))
    frames = json.loads((root / "population-accumulation-frames.json").read_text(encoding="utf-8"))["frames"]
    contact = json.loads((root / "population-contact-density.json").read_text(encoding="utf-8"))
    paths = json.loads((root / "population-path-density.json").read_text(encoding="utf-8"))
    runners = json.loads((root / "population-runner-traffic.json").read_text(encoding="utf-8"))
    representatives = json.loads((root / "representative-paths.json").read_text(encoding="utf-8"))
    handoff = json.loads((root / "aisp-population-geometry-handoff.json").read_text(encoding="utf-8"))

    assert manifest["parentBundleSha256"] == PARENT_BUNDLE_SHA256
    assert manifest["playGeometrySupplementSha256"] == PLAY_GEOMETRY_SHA256
    assert manifest["acceptanceProtocolV2Sha256"] == ACCEPTANCE_PROTOCOL_V2_SHA256
    assert manifest["simulationCount"] == summary["simulationCount"] == 5000
    assert summary["reconstruction"]["allMetricsMatch"] is True
    assert summary["reconstruction"]["deterministicReplay"] is True
    assert summary["illegalStateCount"] == summary["nonterminationCount"] == 0
    assert len(frames) == 100 and frames[-1]["cumulativeSimulationCount"] == 5000
    assert frames[-1]["cumulativeContactPlayCount"] == summary["counts"]["contactPlays"]
    assert frames[-1]["cumulativeGeometryDensity"] == summary["counts"]["geometryBearingPlays"]
    assert frames[-1]["cumulativeScoringPlayCount"] == summary["counts"]["scoringPlays"]
    assert frames[-1]["cumulativeRunnerPathTraffic"] == summary["counts"]["runnerSegments"]
    assert contact["layers"]["ALL"]["count"] == summary["counts"]["geometryBearingPlays"]
    assert sum(row[2] for row in paths["layers"]["ALL"]) == summary["counts"]["geometryBearingPlays"]
    assert sum(runners["allSegments"].values()) == summary["counts"]["runnerSegments"]
    assert set(representatives["selectors"]) == set(summary["representatives"]["selectors"])
    assert representatives["uniquePathCount"] == len(representatives["paths"])
    trace = handoff["modes"]["PLAY_GEOMETRY"]["existingTraceVerification"]
    assert trace["plateAppearances"] == 74 and trace["geometryBearingContactPlays"] == 53
    assert trace["ballTraceForEverySupportedContact"] is True
    assert handoff["loading"]["expectedDecodedMemoryBytesConservative"] <= handoff["loading"]["maximumSupportedTotalDecodedMemoryBytes"]
    for path in representatives["paths"]:
        assert path["events"][-1]["awayScoreAfter"] != path["events"][-1]["homeScoreAfter"]
        for event in path["events"]:
            geometry = event["geometry"]
            for unsupported in ("exitVelocityMph", "launchAngleDegrees", "sprayAngleDegrees", "projectedDistanceFeet", "landingCoordinateMeasured"):
                assert geometry[unsupported] is None


def test_recovered_bullpen_evidence_and_governance_are_explicit() -> None:
    root = _published()
    execution = json.loads(gzip.decompress((root / "execution-authority.json.gz").read_bytes()))
    bullpen = execution["bullpenEvidence"]
    assert bullpen["awayTeam"] == "TOR" and bullpen["homeTeam"] == "ATH"
    assert bullpen["awayMembers"] == bullpen["homeMembers"] == 8
    assert len(bullpen["awayDigest"]) == len(bullpen["homeDigest"]) == 64
    assert bullpen["substitution"] is False
    assert bullpen["postgameProspectiveEvidenceUsed"] is False
    assert execution["developmentAuthority"]["finalOotRowsRead"] == 0
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["operations"]["v18PredictiveModelFits"] == 0
    assert manifest["operations"]["providerCalls"] == 0
    assert manifest["operations"]["aispWrites"] == 0
    assert manifest["operations"]["readinessPolicyStudies"] == 0


def test_required_runner_traffic_categories_are_materialized() -> None:
    root = _published()
    traffic = json.loads((root / "population-runner-traffic.json").read_text(encoding="utf-8"))["requiredTrafficCounts"]
    expected = {
        "HOME_TO_FIRST", "FIRST_TO_SECOND", "SECOND_TO_THIRD", "THIRD_TO_HOME",
        "HOME_TO_SECOND", "HOME_TO_THIRD", "FIRST_TO_THIRD", "FIRST_TO_HOME",
        "SECOND_TO_HOME", "RUNNER_REMOVED_OR_RETIRED", "RUNNER_STRANDED_END_INNING",
    }
    assert set(traffic) == expected
    assert all(traffic[name] > 0 for name in expected)


def test_consumer_fails_closed_and_falls_back_to_broadcast(tmp_path: Path) -> None:
    root = _published()
    copied = tmp_path / "population"
    shutil.copytree(root, copied)
    target = copied / "population-summary.json"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(PopulationGeometryError, match="checksum differs"):
        verify_manifest(copied)
    fallback = load_or_broadcast(copied)
    assert fallback["mode"] == "BROADCAST_REPLAY"
    assert fallback["fallback"] is True


def test_accepted_protocol_and_readiness_cohort_still_verify() -> None:
    acceptance = Path("outputs/mlb-v18-acceptance-protocol-v2/sha256") / ACCEPTANCE_PROTOCOL_V2_SHA256 / "manifest.json"
    accepted = json.loads(acceptance.read_text(encoding="utf-8"))
    assert accepted["contractSha256"] == ACCEPTANCE_PROTOCOL_V2_SHA256
    cohort_root = Path("outputs/mlb-gen1-bet-readiness-cohort/sha256/cd44ef70d6d4a5f3258cfad2cd6222accc5a39431d131184cf7b851ecced5785")
    cohort = json.loads((cohort_root / "cohort.json").read_text(encoding="utf-8"))
    body = {key: value for key, value in cohort.items() if key != "cohortSha256"}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == cohort["cohortSha256"]
