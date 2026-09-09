"""One real import-contract, population-accounting and frozen-engine reconstruction."""
from __future__ import annotations
import json
from pathlib import Path
import joblib
import numpy as np
from server.sports_nfl_m1.labs_simulation import (
    empirical_scores, file_record, immutable_json, summarize_scores, verify_object,
    utc,
)
from server.sports_nfl_m1.labs_simulation_drives import simulate_drive_game, verify_drive_accounting


def verify() -> dict:
    output = Path("outputs/nfl-labs-simulation-v1")
    current = json.loads((output / "CURRENT.json").read_bytes())
    score = json.loads(Path(current["path"]).read_bytes())
    drive = json.loads(Path(current["driveHandoffPath"]).read_bytes())
    first = json.loads((output / "sha256/00728ab5854915c3831c9bd67643b64809598566fab90c9ded756995a626bb16/handoff.json").read_bytes())
    rerun = json.loads((output / "sha256/b2c7d00e7b567d55ce42186395ed0175f52b55d4f08de3ac998fa4f96f6d68fc/handoff.json").read_bytes())
    assert first["artifacts"] == rerun["artifacts"]
    maximum = 0.0
    for ref in score["artifacts"]:
        artifact = verify_object(ref)
        assert file_record(Path(artifact["sourceForecast"]["path"])) == {k:artifact["sourceForecast"][k] for k in ("path","sha256","byteCount")}
        home, away = empirical_scores({"simulator": {"simulationCount": artifact["drawCount"]}, "jointScoreDistribution": artifact["jointScoreDistribution"]})
        observed = summarize_scores(home,away)
        maximum = max(maximum,max(abs(observed[k]-artifact["scoreSummary"][k]) for k in observed))
    all_reps = 0
    creation_times = set()
    for ref in drive["artifacts"]:
        artifact = verify_object(ref)
        assert utc(artifact["inferenceStartedUtc"]) <= utc(artifact["forecastCreatedUtc"]) <= utc(artifact["publishedAtUtc"]) < utc(artifact["scheduledStartUtc"])
        creation_times.add(artifact["forecastCreatedUtc"])
        assert artifact["model"]["engineId"] == "NFL_DEVELOPMENT_CONDITIONAL_DRIVE_V2"
        verify_object(artifact["predecessorArtifact"])
        finals = artifact["populationFinals"]
        home, away = np.array([g["homeScore"] for g in finals]), np.array([g["awayScore"] for g in finals])
        assert len(finals) == artifact["drawCount"]
        observed = summarize_scores(home,away)
        maximum = max(maximum,max(abs(observed[k]-artifact["scoreSummary"][k]) for k in observed))
        assert len(artifact["simulatedDrives"]) == 6
        assert len({g["simulationIndex"] for g in artifact["simulatedDrives"]}) == 6
        for game in artifact["simulatedDrives"]:
            verify_drive_accounting(game)
            assert game["homeScore"] == finals[game["simulationIndex"]]["homeScore"]
            assert game["awayScore"] == finals[game["simulationIndex"]]["awayScore"]
            all_reps += 1
    artifact = verify_object(drive["artifacts"][0])
    model = joblib.load(artifact["model"]["modelArtifact"]["path"])
    saved = artifact["simulatedDrives"][0]
    aliases = {"LAR": "LA", "WSH": "WAS"}
    home = artifact["homeTeam"]["abbreviation"]; away = artifact["awayTeam"]["abbreviation"]
    actual = simulate_drive_game(model,home_team=aliases.get(home,home),away_team=aliases.get(away,away),season=2026,postseason=False,
                                 seed=saved["seed"],pace_multiplier=artifact["scenario"]["paceDurationMultiplier"])
    assert actual == {k:v for k,v in saved.items() if k not in ("label","simulationIndex")}
    assert maximum == 0
    result = {"schemaVersion":"NFL_LABS_SIMULATION_VERIFICATION_V2", "scoreSupplementCount":len(score["artifacts"]),
              "driveSupplementCount":len(drive["artifacts"]),"driveRepresentativeGamesVerified":all_reps,
              "populationSummaryMaxAbsoluteMismatch":maximum,"savedM1DistributionIdempotencyExact":True,
              "frozenDriveSequenceReconstructionExact":True,"originalForecastObjectsUnchanged":True,
              "distinctActualForecastCreationTimestamps":len(creation_times), "allInferenceCreationPublicationBeforeKickoff":True,
              "predecessorArtifactsVerifiedUnchanged":True,
              "sealedOotRead":False,"modelFitsDuringVerification":0,"aispActivity":False}
    immutable_json(output / "verification-v2.json",result)
    return result


if __name__ == "__main__": print(json.dumps(verify(),indent=2))
