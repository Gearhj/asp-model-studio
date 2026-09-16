"""One saved-fold historical inference fixture, not a retroactive live forecast."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from server.sports_nfl_m1.semantic_lab import OUTPUT, digest, immutable_json, _plain_json
from server.sports_nfl_m1.semantic_publisher import forecast_one


def verify():
    runs = sorted((OUTPUT / "runs").glob("*/XGBOOST_C1/fold-2020.joblib"), key=lambda p: p.stat().st_mtime)
    path = runs[-1]
    run = path.parent.parent
    artifact = joblib.load(path)
    frame = pd.read_parquet(run / "pregame_feature_states.parquet", filters=[("season", "=", 2020)])
    source = frame.iloc[0].to_dict()
    # No label payload is admitted to the publisher.
    source.pop("home_points"); source.pop("away_points")
    feature_state = _plain_json(source)
    event_day = pd.Timestamp(source["game_date"])
    kickoff = event_day.replace(hour=23).tz_localize("UTC")
    now = (event_day - pd.Timedelta(days=1)).replace(hour=12).tz_localize("UTC")
    cutoff = now - pd.Timedelta(hours=1)
    max_evidence = max(pd.Timestamp(source[f"{side}__last_passer_date"]) for side in ("home", "away")).tz_localize("UTC")
    event = {"eventId": source["canonical_game_id"], "homeTeamId": source["canonical_home_team_id"], "awayTeamId": source["canonical_away_team_id"], "scheduledStartUtc": kickoff.isoformat()}
    packet = {"contract": "NFL_SEMANTIC_PREGAME_STATE_V1", "eventId": event["eventId"], "authorizedForCurrentResearchInference": True,
              "sourceCutoffUtc": cutoff.isoformat(), "maximumCompletedGameEvidenceUtc": max_evidence.isoformat(), "featureState": feature_state}
    before = forecast_one(artifact, digest(path), event, packet, now=now.to_pydatetime(), historical_fixture=True)
    after = forecast_one(joblib.load(path), digest(path), event, packet, now=now.to_pydatetime(), historical_fixture=True)
    if before != after:
        raise ValueError("PUBLICATION_RELOAD_MISMATCH")
    pmf = before["rawDistribution"]["jointScorePmf"]
    total = sum(item["probability"] for item in pmf)
    for relation, key in ((lambda h,a:h>a, "homeWinProbability"), (lambda h,a:h<a, "awayWinProbability"), (lambda h,a:h==a, "tieProbability")):
        recomputed = sum(item["probability"] for item in pmf if relation(item["homeScore"], item["awayScore"]))
        if abs(recomputed - before["rawDistribution"][key]) > 1e-12:
            raise ValueError("PUBLISHED_PMF_MISMATCH")
    result = {"contract": "NFL_SEMANTIC_PUBLISHER_RELOAD_FIXTURE_V1", "historicalDeterministicFixtureOnly": True,
              "notAnActualPregamePublication": True, "notForCurrentSlateImport": True,
              "fixtureKickoffSyntheticTimeOnRealGameDate": True, "eventId": event["eventId"], "sourceFoldArtifact": str(path),
              "sourceFoldArtifactSha256": digest(path), "draws": before["drawCount"], "seed": before["seed"],
              "reloadMismatch": 0, "jointMass": total, "probabilityPmfMismatchMaximum": 1e-12,
              "rawProbabilities": {key: before["rawDistribution"][key] for key in ("homeWinProbability", "awayWinProbability", "tieProbability")},
              "separateCalibratedProbabilityNotClaimedAsSimulation": True, "targetPayloadReadByPublisher": False,
              "researchOnly": True, "finalOotRead": False}
    sha = immutable_json(OUTPUT / "verification" / "publisher-reload-fixture.json", result)
    return {"path": str(OUTPUT / "verification" / "publisher-reload-fixture.json"), "sha256": sha, **result}


if __name__ == "__main__":
    print(json.dumps(verify()))
