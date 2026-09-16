"""Immutable publication of supported semantic candidates or explicit skips.

This does not read protected initialization history. A caller may supply a
separately authorized, content-addressed pregame state packet. Without one the
rolling current slate is reported as skipped, never filled from stale2024.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from server.audit_assurance.canonical import canonical_json_bytes
from .data_authority import resolve_nfl_m1_authority
from .semantic_lab import OUTPUT, digest, immutable_json

UTC = timezone.utc
AUTHORITY = {"status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "wageringAuthority": False, "executionAllowedInAISP": False}


def utc(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return result.astimezone(UTC)


def next_slate(now: datetime):
    authority = resolve_nfl_m1_authority(deep_verify=False)
    # Only schedule identity/time columns for current/future seasons, no scores
    # and no2025rows, are physically projected into memory.
    frame = pd.read_parquet(authority.schedule_path, columns=["game_id", "season", "week", "gameday", "gametime", "home_team", "away_team", "game_type", "updated"], filters=[("season", ">=", max(2026, now.year - 1))])
    events = []
    canonical = {"OAK": "LV", "SD": "LAC", "STL": "LAR", "LA": "LAR"}
    for row in frame.to_dict("records"):
        if not row.get("gametime") or str(row["gametime"]) in {"nan", "None"}:
            continue
        kickoff = datetime.fromisoformat(str(row["gameday"])[:10] + "T" + str(row["gametime"])[:5]).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
        if kickoff <= now:
            continue
        events.append({"eventId": row["game_id"], "season": int(row["season"]), "week": int(row["week"]), "gameType": str(row["game_type"]),
                       "homeTeamId": canonical.get(row["home_team"], row["home_team"]), "awayTeamId": canonical.get(row["away_team"], row["away_team"]),
                       "scheduledStartUtc": kickoff.isoformat(), "scheduleSourceUpdated": str(row.get("updated")), "scheduleManifestSha256": authority.schedule_manifest_sha256})
    events.sort(key=lambda row: (row["scheduledStartUtc"], row["eventId"]))
    if not events:
        return []
    first = events[0]
    return [event for event in events if (event["season"], event["week"], event["gameType"]) == (first["season"], first["week"], first["gameType"])]


def forecast_one(artifact, model_sha: str, event: dict, state_packet: dict, *, now: datetime, seed: int = 731001, draws: int = 2000, historical_fixture: bool = False):
    now, kickoff = utc(now), utc(event["scheduledStartUtc"])
    cutoff = utc(state_packet["sourceCutoffUtc"])
    if not cutoff <= now < kickoff:
        raise ValueError("NOT_A_VALID_PREGAME_PUBLICATION")
    if state_packet.get("contract") != "NFL_SEMANTIC_PREGAME_STATE_V1" or state_packet.get("authorizedForCurrentResearchInference") is not True:
        raise ValueError("AUTHORIZED_PREGAME_STATE_REQUIRED")
    if state_packet.get("eventId") != event["eventId"]:
        raise ValueError("PREGAME_STATE_EVENT_MISMATCH")
    game_zone = ZoneInfo("America/New_York")
    if utc(state_packet["maximumCompletedGameEvidenceUtc"]).astimezone(game_zone).date() >= kickoff.astimezone(game_zone).date():
        raise ValueError("SAME_DATE_OUTCOME_EVIDENCE_FORBIDDEN")
    if utc(state_packet["maximumCompletedGameEvidenceUtc"]) > cutoff:
        raise ValueError("EVIDENCE_AFTER_SOURCE_CUTOFF")
    if not historical_fixture:
        # No source registration currently publishes this full semantic state.
        # A caller's Boolean cannot grant access to protected initialization
        # data or stand in for verified source receipts and checksums. Keep
        # production packet injection disabled until that one missing link is
        # registered. The real frozen pipeline is exercised by labeled fixtures.
        raise ValueError("SEMANTIC_SOURCE_PACKET_AUTHORITY_NOT_REGISTERED")
    if pd.Timestamp(artifact.model.treatment.training_end).date() > cutoff.date():
        raise ValueError("TRAINING_AFTER_SOURCE_CUTOFF")
    row = dict(state_packet["featureState"])
    if {"home_points", "away_points", "home_win", "tie_game", "score_differential", "total_points", "outcome_class"} & set(row):
        raise ValueError("PREGAME_STATE_CONTAINS_TARGET_PAYLOAD")
    if str(row.get("canonical_game_id")) != str(event["eventId"]) or str(row.get("canonical_home_team_id")) != str(event["homeTeamId"]) or str(row.get("canonical_away_team_id")) != str(event["awayTeamId"]):
        raise ValueError("CANONICAL_TEAM_OR_EVENT_MISMATCH")
    frame = pd.DataFrame([row])
    frame["game_date"] = pd.to_datetime(frame.game_date)
    if frame.iloc[0].game_date.date() != kickoff.astimezone(ZoneInfo("America/New_York")).date():
        raise ValueError("SCHEDULE_DATE_MISMATCH")
    if not historical_fixture and datetime.now(UTC) >= kickoff:
        raise ValueError("KICKOFF_PASSED_BEFORE_INFERENCE")
    predicted = artifact.predict(frame, seed=seed, draws=draws)
    if not historical_fixture and datetime.now(UTC) >= kickoff:
        raise ValueError("KICKOFF_PASSED_DURING_INFERENCE")
    sim = predicted["simulation"]
    home, away = sim.home[0], sim.away[0]
    # The published raw PMF/probabilities agree exactly. Numerical flooring for
    # evaluation log loss is not an invented tie-support mass in the export.
    raw = np.asarray([np.mean(home < away), np.mean(home == away), np.mean(home > away)])
    calibrated = predicted["separateCalibratedProbability"][0]
    result = {"contract": "NFL_SEMANTIC_RESEARCH_FORECAST_V1", **event, **AUTHORITY,
              "forecastCreatedUtc": now.isoformat(), "sourceCutoffUtc": cutoff.isoformat(),
              "maximumCompletedGameEvidenceUtc": state_packet["maximumCompletedGameEvidenceUtc"],
              "inputStateSha256": hashlib.sha256(canonical_json_bytes(state_packet)).hexdigest(),
              "model": {"modelId": artifact.pipeline_id, "binarySha256": model_sha, "trainingEnd": artifact.model.treatment.training_end},
              "seed": seed, "drawCount": draws, "distributionMethod": sim.contract_version,
              "scoreMeanEstimator": {"home": float(predicted["scoreMeans"][0, 0]), "away": float(predicted["scoreMeans"][0, 1])},
              "rawDistribution": {"homeWinProbability": float(raw[2]), "awayWinProbability": float(raw[0]), "tieProbability": float(raw[1]),
                  "expectedHomeScore": float(home.mean()), "expectedAwayScore": float(away.mean()),
                  "expectedMarginHomeMinusAway": float((home - away).mean()), "expectedTotal": float((home + away).mean()),
                  "jointScorePmf": [{"homeScore": h, "awayScore": a, "probability": p} for (h, a), p in sim.joint_pmf(0).items()],
                  "marginQuantiles": np.quantile(home-away, [.05,.25,.5,.75,.95]).tolist(), "totalQuantiles": np.quantile(home+away,[.05,.25,.5,.75,.95]).tolist()},
              "separatelyCalibratedProbabilities": {"homeWinProbability": float(calibrated[2]), "awayWinProbability": float(calibrated[0]), "tieProbability": float(calibrated[1]), "isJointSimulationDistribution": False},
              "inputReadiness": "AUTHORIZED_SEMANTIC_FEATURE_STATE", "treatmentBranchCounts": predicted["branchCounts"]}
    numerical_identity = {key: value for key, value in result.items() if key != "forecastCreatedUtc"}
    result["forecastId"] = "nfl-semantic:" + hashlib.sha256(canonical_json_bytes(numerical_identity)).hexdigest()
    if historical_fixture:
        result["historicalDeterministicFixtureOnly"] = True
        result["notAnActualPregamePublication"] = True
    return result


def publish_current(*, now: datetime | None = None, state_packets: dict | None = None, model_paths: list[Path] | None = None, output: Path = OUTPUT / "current-publications"):
    now = utc(now or datetime.now(UTC))
    events = next_slate(now)
    states = state_packets or {}
    # Names/checksums may be bound while the input-authority link is missing;
    # do not load or execute estimators for an all-skip publication.
    selected_models = [{"path": str(path), "sha256": digest(path)} for path in (model_paths or [])]
    forecasts, skips = [], []
    for event in events:
        packet = states.get(event["eventId"])
        if not packet:
            skips.append({**event, "reason": "MISSING_AUTHORIZED_2025_INITIALIZATION_AND_CURRENT_SEMANTIC_STATE", "detail": "New semantic model requires previous-season/team and player sufficient statistics. No sealed2025 source accessed; legacy197median-filled inputs do not supply this authority."})
            continue
        skips.append({**event, "reason": "SEMANTIC_SOURCE_PACKET_AUTHORITY_NOT_REGISTERED", "detail": "A supplied Boolean is not a verified source receipt. Current packet injection remains disabled until the source registration and checksum lineage exist."})
    ready = []
    for forecast in forecasts:
        if datetime.now(UTC) >= utc(forecast["scheduledStartUtc"]):
            skips.append({"eventId": forecast["eventId"], "modelId": forecast["model"]["modelId"], "reason": "KICKOFF_PASSED_BEFORE_IMMUTABLE_PUBLICATION"})
        else:
            ready.append(forecast)
    forecasts = ready
    body = {"contract": "NFL_SEMANTIC_CURRENT_SLATE_PUBLICATION_V1", "publishedAtUtc": datetime.now(UTC).isoformat(), **AUTHORITY,
            "eventCount": len(events), "forecastCount": len(forecasts), "skipCount": len(skips), "forecasts": forecasts, "skips": skips,
            "supportedInputContract": "NFL_SEMANTIC_PREGAME_STATE_V1", "sourceAsOfNotAdvancedByPublication": True,
            "selectedModelArtifacts": selected_models, "currentInputAuthorityRegistered": False,
            "legacyForecastBundlesModified": False, "sealedOotAccessed": False}
    sha = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    folder = output / "sha256" / sha
    artifact_path = folder / "publication.json"
    immutable_json(artifact_path, body)
    manifest = {"contract": "NFL_SEMANTIC_PUBLICATION_MANIFEST_V1", **AUTHORITY, "publicationSha256": sha,
                "files": [{"path": "publication.json", "sha256": sha, "byteCount": artifact_path.stat().st_size}],
                "publishedAtUtc": body["publishedAtUtc"], "forecastCount": len(forecasts), "eventCount": len(events), "skipCount": len(skips)}
    manifest_sha = immutable_json(folder / "manifest.json", manifest)
    output.mkdir(parents=True, exist_ok=True)
    (output / "current.json").write_bytes(canonical_json_bytes({"publicationPath": str(artifact_path), "publicationSha256": sha, "manifestPath": str(folder / "manifest.json"), "manifestSha256": manifest_sha}))
    return {"publicationPath": str(artifact_path), "publicationSha256": sha, "manifestSha256": manifest_sha,
            "forecastCount": len(forecasts), "skipCount": len(skips), "eventCount": len(events)}


if __name__ == "__main__":
    print(json.dumps(publish_current()))
