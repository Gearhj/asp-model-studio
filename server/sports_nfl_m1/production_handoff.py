"""Build an immutable, prospective NFL M1 production-authority handoff.

This module never fits or executes a model.  It verifies the existing research
exchange, reconstructs each retained paired-score population from whole draw
counts, and publishes a separately identified authority document for AISP.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_gold.nfl_shadow_exchange import (
    ASP_SPORTS_GAME_FORECAST_V1,
    BUNDLE_OBJECT_FAMILY,
    verify_nfl_2026_research_shadow_locator,
    verify_sports_forecast_bundle,
)
from server.sports_nfl_m1.prospective_shadow import (
    MODEL_BINARY_SHA256,
    MODEL_CANDIDATE,
    MODEL_MANIFEST_SHA256,
    SIMULATION_DRAWS,
)

HANDOFF_CONTRACT = "ASP_NFL_M1_PRODUCTION_HANDOFF_V1"
HANDOFF_STATUS = "NFL_M1_PRODUCTION_BASELINE_PROSPECTIVE_MONITORING"
DISCOVERY_CONTRACT = "ASP_NFL_M1_PRODUCTION_DISCOVERY_SNAPSHOT_V1"
MODEL_ID = "NFL_M1_XGBOOST"
CONFIGURATION_ID = "NFL_M1_2026_RESEARCH_SHADOW_V1"
EXCHANGE_FAMILY = "nfl-m1-production-v1"
TIE_POLICY = {
    "outcomes": ["HOME", "TIE", "AWAY"],
    "finalTieOutcome": "TIE",
    "probabilityMass": "RETAINED_NOT_REDISTRIBUTED",
    "twoWayMoneylineSettlement": "PUSH_REFUND_WHEN_GOVERNING_HOUSE_RULES_REQUIRE",
    "validation": "DISCRETE_TIE_MASS_NOT_SEPARATELY_VALIDATED",
}


class NflProductionHandoffError(ValueError):
    """The existing forecast authority cannot support the handoff."""


def _utc(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise NflProductionHandoffError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NflProductionHandoffError(f"{label} has no timezone")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _population(forecast: Mapping[str, Any]) -> dict[str, Any]:
    simulator = forecast.get("simulator") or {}
    draws = int(simulator.get("completedSimulations") or 0)
    if draws != SIMULATION_DRAWS or draws != int(simulator.get("simulationCount") or -1):
        raise NflProductionHandoffError("forecast draw count differs from the frozen 10,000-draw contract")
    cells: list[dict[str, int]] = []
    for row in forecast.get("jointScoreDistribution") or ():
        exact = float(row["probability"]) * draws
        count = round(exact)
        if abs(exact - count) > 1e-6 or count < 0:
            raise NflProductionHandoffError("joint score probability is not a whole-draw count")
        if count:
            cells.append({
                "awayScore": int(row["awayScore"]),
                "count": count,
                "homeScore": int(row["homeScore"]),
            })
    cells.sort(key=lambda row: (row["awayScore"], row["homeScore"]))
    if not cells or sum(row["count"] for row in cells) != draws:
        raise NflProductionHandoffError("joint score cells do not reconcile to draw count")
    if len({(row["awayScore"], row["homeScore"]) for row in cells}) != len(cells):
        raise NflProductionHandoffError("joint score population contains duplicate cells")

    home_wins = sum(row["count"] for row in cells if row["homeScore"] > row["awayScore"])
    away_wins = sum(row["count"] for row in cells if row["awayScore"] > row["homeScore"])
    ties = draws - home_wins - away_wins
    expected_home = sum(row["homeScore"] * row["count"] for row in cells) / draws
    expected_away = sum(row["awayScore"] * row["count"] for row in cells) / draws
    expected = (
        ("homeWinProbability", home_wins / draws),
        ("awayWinProbability", away_wins / draws),
        ("tieProbability", ties / draws),
        ("expectedHomeScore", expected_home),
        ("expectedAwayScore", expected_away),
    )
    for name, value in expected:
        if not math.isclose(float(forecast[name]), value, rel_tol=0.0, abs_tol=1e-12):
            raise NflProductionHandoffError(f"{name} differs from the paired population")
    if not math.isclose(home_wins / draws + away_wins / draws + ties / draws, 1.0, abs_tol=1e-12):
        raise NflProductionHandoffError("three-way probability mass differs")

    def counts_for(kind: str) -> dict[int, int]:
        result: dict[int, int] = defaultdict(int)
        for cell in cells:
            value = (cell["homeScore"] - cell["awayScore"] if kind == "margin"
                     else cell["homeScore"] + cell["awayScore"])
            result[value] += cell["count"]
        return dict(result)

    supplied = {
        "margin": (forecast.get("scoreMarginDistribution") or (), "homeMinusAway"),
        "total": (forecast.get("totalScoreDistribution") or (), "totalScore"),
    }
    for kind, (rows, coordinate) in supplied.items():
        observed: dict[int, int] = {}
        for row in rows:
            exact = float(row["probability"]) * draws
            count = round(exact)
            if abs(exact - count) > 1e-6:
                raise NflProductionHandoffError(f"{kind} probability is not a whole-draw count")
            observed[int(row[coordinate])] = count
        if observed != counts_for(kind):
            raise NflProductionHandoffError(f"{kind} distribution differs from joint population")
    digest = hashlib.sha256(canonical_json_bytes(cells)).hexdigest()
    return {
        "drawCount": draws,
        "populationSha256": digest,
        "expectedHomeScore": expected_home,
        "expectedAwayScore": expected_away,
        "homeWinProbability": home_wins / draws,
        "awayWinProbability": away_wins / draws,
        "tieProbability": ties / draws,
        "jointCellCount": len(cells),
    }


def _orientation(forecast: Mapping[str, Any]) -> None:
    event = str(forecast.get("eventId") or "")
    parts = event.split("_")
    if len(parts) != 4:
        raise NflProductionHandoffError(f"unsupported event identity {event!r}")
    away = str((forecast.get("awayTeam") or {}).get("abbreviation") or "")
    home = str((forecast.get("homeTeam") or {}).get("abbreviation") or "")
    aliases = {"LAR": "LA"}
    if parts[2] != aliases.get(away, away) or parts[3] != aliases.get(home, home):
        raise NflProductionHandoffError(f"participant orientation differs for {event}")
    if forecast.get("sourceEventId") != f"nflverse:{event}":
        raise NflProductionHandoffError(f"source event identity differs for {event}")


def build_discovery_snapshot(
    exchange_root: Path,
    *,
    effective_from_utc: datetime,
    issued_at_utc: datetime,
) -> dict[str, Any]:
    """Verify current immutable bundles and select one controlling revision per future game."""

    root = Path(exchange_root).resolve()
    locator = verify_nfl_2026_research_shadow_locator(root)
    locator_path = root / BUNDLE_OBJECT_FAMILY / "nfl-2026-research-shadow-index.json"
    locator_sha = hashlib.sha256(locator_path.read_bytes()).hexdigest()
    candidates: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for bundle_sha in locator["currentBundleSha256s"]:
        verified = verify_sports_forecast_bundle(root, bundle_sha)
        for forecast in verified.record["forecasts"]:
            kickoff = _utc(forecast["scheduledStartUtc"], "scheduledStartUtc")
            if kickoff < effective_from_utc:
                continue
            candidates[str(forecast["eventId"])].append((dict(forecast), bundle_sha))
    if not candidates:
        raise NflProductionHandoffError("no forecasts kick off on or after effectiveFromUtc")

    selected = []
    for event, rows in sorted(candidates.items()):
        forecast, bundle_sha = max(
            rows,
            key=lambda item: (
                _utc(item[0]["availableAsOfUtc"], "availableAsOfUtc"),
                int(item[0]["snapshotVersion"]),
                str(item[0]["forecastId"]),
            ),
        )
        _orientation(forecast)
        schedule_as_of = _utc(forecast["scheduleAsOfUtc"], "scheduleAsOfUtc")
        source_cutoff = _utc(forecast["sourceCutoffUtc"], "sourceCutoffUtc")
        forecast_cutoff = _utc(forecast["forecastCutoffUtc"], "forecastCutoffUtc")
        published = _utc(forecast["availableAsOfUtc"], "availableAsOfUtc")
        kickoff = _utc(forecast["scheduledStartUtc"], "scheduledStartUtc")
        if not schedule_as_of <= source_cutoff <= forecast_cutoff <= published < kickoff:
            raise NflProductionHandoffError(f"forecast chronology differs for {event}")
        engine = forecast.get("engine") or {}
        if (engine.get("engineId") != MODEL_ID
                or engine.get("engineVersion") != CONFIGURATION_ID
                or engine.get("modelBinarySha256") != MODEL_BINARY_SHA256
                or engine.get("modelManifestSha256") != MODEL_MANIFEST_SHA256):
            raise NflProductionHandoffError(f"model identity differs for {event}")
        if not bool((forecast.get("readiness") or {}).get("isReady")):
            raise NflProductionHandoffError(f"forecast is not ready for {event}")
        population = _population(forecast)
        selected.append({
            "eventId": event,
            "sourceEventId": forecast["sourceEventId"],
            "awayTeam": forecast["awayTeam"]["abbreviation"],
            "homeTeam": forecast["homeTeam"]["abbreviation"],
            "kickoffUtc": _utc_text(kickoff),
            "forecastId": forecast["forecastId"],
            "snapshotType": forecast["snapshotType"],
            "snapshotVersion": forecast["snapshotVersion"],
            "sourceCutoffUtc": _utc_text(source_cutoff),
            "publishedUtc": _utc_text(published),
            "sourceBundleSha256": bundle_sha,
            **population,
        })
    selected.sort(key=lambda row: (row["kickoffUtc"], row["eventId"]))
    return {
        "contract": DISCOVERY_CONTRACT,
        "createdAtUtc": _utc_text(issued_at_utc),
        "effectiveFromUtc": _utc_text(effective_from_utc),
        "sourceLocator": {
            "relativePath": f"{BUNDLE_OBJECT_FAMILY}/nfl-2026-research-shadow-index.json",
            "physicalSha256": locator_sha,
            "updatedAtUtc": locator["updatedAtUtc"],
        },
        "model": {
            "modelId": MODEL_ID,
            "configurationId": CONFIGURATION_ID,
            "modelRevision": MODEL_CANDIDATE,
            "modelArtifactSha256": MODEL_BINARY_SHA256,
            "modelManifestSha256": MODEL_MANIFEST_SHA256,
            "featureContractSha256": locator["featureContractSha256"],
            "calibration": "NONE",
        },
        "population": {
            "drawCount": SIMULATION_DRAWS,
            "simulatorId": "NFL_M1_EMPIRICAL_PAIRED_RESIDUAL",
            "simulatorVersion": "NFL_M1_EMPIRICAL_CORRELATED_RESIDUAL_V1",
            "tiePolicy": TIE_POLICY,
        },
        "selectionRule": "LATEST_PRE_KICKOFF_PUBLICATION_PER_MODEL_IDENTITY_AT_SNAPSHOT_CREATION",
        "forecastCount": len(selected),
        "forecasts": selected,
    }


def build_handoff(
    discovery: Mapping[str, Any],
    *,
    discovery_path: str,
    discovery_sha256: str,
    issued_at_utc: datetime,
    issuer_revision: str,
) -> dict[str, Any]:
    """Return the exact AISP adapter contract plus auditable seed populations."""

    return {
        "contract": HANDOFF_CONTRACT,
        "status": HANDOFF_STATUS,
        "modelId": MODEL_ID,
        "configurationId": CONFIGURATION_ID,
        "modelRevision": MODEL_CANDIDATE,
        "modelArtifactSha256": MODEL_BINARY_SHA256,
        "modelManifestSha256": MODEL_MANIFEST_SHA256,
        "featureContractSha256": discovery["model"]["featureContractSha256"],
        "discoveryPath": discovery_path,
        "discoveryIndexSha256": discovery_sha256,
        "drawCount": SIMULATION_DRAWS,
        "tiePolicy": TIE_POLICY,
        "forecastContract": ASP_SPORTS_GAME_FORECAST_V1,
        "effectiveFromUtc": discovery["effectiveFromUtc"],
        "calibrationAuthority": {
            "method": "NONE",
            "status": "UNCALIBRATED_PROVISIONAL_BASELINE",
            "minimumSettledGamesForPublishedCalibration": 100,
        },
        "issuedAtUtc": _utc_text(issued_at_utc),
        "issuer": {
            "system": "ASP_MODEL_STUDIO",
            "gitRevision": issuer_revision,
        },
        "playLevelSubstitutionAllowed": False,
        # A rolling owner can publish a later pre-kickoff revision whose id and
        # population do not exist yet.  AISP's per-forecast verifier still
        # requires the exact model/artifact/draw count and independently hashes
        # its paired population.  Pre-pinning this optional map would make every
        # legitimate successor fail FORECAST_NOT_LISTED.
        "forecastPopulations": {},
        "seedForecastPopulationEvidence": [
            {
                "eventId": row["eventId"],
                "forecastId": row["forecastId"],
                "sourceBundleSha256": row["sourceBundleSha256"],
                "populationSha256": row["populationSha256"],
                "drawCount": row["drawCount"],
            }
            for row in discovery["forecasts"]
        ],
        "authority": {
            "designation": "CONTROLLING_OPERATIONAL_BASELINE_WITH_PROSPECTIVE_MONITORING",
            "profitabilityClaim": False,
            "personnelCaptureIncluded": False,
            "playLevelSimulatorIncluded": False,
        },
        "monitoring": {
            "scoreEachGameIndependently": True,
            "firstReviewSettledGames": 50,
            "calibrationReviewSettledGames": 100,
            "metrics": [
                "THREE_WAY_LOG_LOSS", "THREE_WAY_SUMMED_BRIER", "CALIBRATION",
                "WINNER_ACCURACY", "HOME_AWAY_SCORE_ERROR", "MARGIN_ERROR",
                "TOTAL_ERROR", "STORED_LINE_WIN_LOSS_PUSH",
            ],
        },
        "rollback": {
            "status": "NFL_M1_SHADOW_ONLY",
            "preserveForecastsScoresAndEvidence": True,
            "method": "REMOVE_OR_REPLACE_THE_AISP_OPERATOR_PIN_WITH_A_HASH_PINNED_SHADOW_HANDOFF",
        },
    }


def _write_immutable(root: Path, family: str, name: str, payload: bytes) -> tuple[str, Path, bool]:
    digest = hashlib.sha256(payload).hexdigest()
    parent = root / EXCHANGE_FAMILY / family / "sha256"
    final = parent / digest
    target = final / name
    parent.mkdir(parents=True, exist_ok=True)
    created = False
    if not final.exists():
        staging = parent / f".staging-{uuid.uuid4().hex}"
        staging.mkdir(parents=False, exist_ok=False)
        try:
            with (staging / name).open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.replace(staging, final)
                created = True
            except OSError:
                if not final.exists():
                    raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    if not target.is_file() or target.read_bytes() != payload:
        raise NflProductionHandoffError(f"immutable {family} bytes differ")
    return digest, target, created


def publish_handoff(
    exchange_root: Path,
    *,
    effective_from_utc: datetime,
    issued_at_utc: datetime,
    issuer_revision: str,
) -> dict[str, Any]:
    root = Path(exchange_root).resolve()
    discovery = build_discovery_snapshot(
        root, effective_from_utc=effective_from_utc, issued_at_utc=issued_at_utc
    )
    discovery_bytes = canonical_json_bytes(discovery)
    discovery_sha, discovery_file, discovery_created = _write_immutable(
        root, "discovery", "discovery-index.json", discovery_bytes
    )
    discovery_path = discovery_file.relative_to(root).as_posix()
    handoff = build_handoff(
        discovery,
        discovery_path=discovery_path,
        discovery_sha256=discovery_sha,
        issued_at_utc=issued_at_utc,
        issuer_revision=issuer_revision,
    )
    handoff_bytes = canonical_json_bytes(handoff)
    handoff_sha, handoff_file, handoff_created = _write_immutable(
        root, "handoffs", "handoff.json", handoff_bytes
    )
    return {
        "contract": "ASP_NFL_M1_PRODUCTION_PUBLICATION_RECEIPT_V1",
        "status": "PUBLISHED_AWAITING_AISP_OPERATOR_PIN",
        "effectiveFromUtc": discovery["effectiveFromUtc"],
        "forecastCount": discovery["forecastCount"],
        "discoveryPath": discovery_path,
        "discoveryIndexSha256": discovery_sha,
        "discoveryCreated": discovery_created,
        "handoffPath": handoff_file.relative_to(root).as_posix(),
        "handoffSha256": handoff_sha,
        "handoffBytes": len(handoff_bytes),
        "handoffCreated": handoff_created,
        "seedForecastPopulationCount": len(handoff["seedForecastPopulationEvidence"]),
    }


__all__ = [
    "CONFIGURATION_ID", "DISCOVERY_CONTRACT", "HANDOFF_CONTRACT", "HANDOFF_STATUS",
    "MODEL_ID", "NflProductionHandoffError", "TIE_POLICY", "build_discovery_snapshot",
    "build_handoff", "publish_handoff",
]
