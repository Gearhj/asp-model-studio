"""Read-only audit of one retained paired-score population per supported sport.

This opens forecast artifacts only.  It does not read results, run models, call
providers, mutate exchange discovery, or write AISP.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.sports_shared.market_probabilities import JointScorePopulation


NFL_PACKAGE = "5c45928219f5c893e0f2acb9572622ff93f0e57dc4c43a00de840ce92e2ff117"
NBA_PACKAGE = "00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d"
CFB_PACKAGE = "223bbc35becc894560cc255dd7b786d2921c3201d63875c0af4a1af4e0b3ff76"
MLB_OBJECT = "2f07648c51e830736d65ff37689c563bb2195ec767090d14ecc8e905968cbdac"


def read_json(path: Path):
    return json.loads(path.read_bytes())


def physical(path: Path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def cells(away, home):
    count = Counter(zip((int(x) for x in away), (int(x) for x in home)))
    return [{"awayScore": away_score, "homeScore": home_score, "count": n}
            for (away_score, home_score), n in sorted(count.items())]


def probabilities(population: JointScorePopulation):
    n = population.draw_count
    home = sum(cell.count for cell in population.cells if cell.home_score > cell.away_score) / n
    away = sum(cell.count for cell in population.cells if cell.away_score > cell.home_score) / n
    tie = sum(cell.count for cell in population.cells if cell.away_score == cell.home_score) / n
    return {"home": home, "away": away, "tie": tie}


def require_close(left, right, field):
    if abs(float(left) - float(right)) > 1e-12:
        raise ValueError(f"{field} differs: {left} != {right}")


def audit(studio: Path, exchange: Path):
    rows = []

    root = studio / "outputs/mlb-v18-current-state-pipeline-v1/objects/sha256" / MLB_OBJECT
    forecast = read_json(root / "forecast.json")
    execution = read_json(root / "execution-inputs.json")
    raw = execution["population"]
    pop = JointScorePopulation.from_cells(
        sport="MLB", game_id=forecast["gameId"], forecast_id=f"mlb-v18-daily-game-{MLB_OBJECT[:24]}",
        model_id="MLB_V18_HGB_PA", configuration_id="UNRESTRICTED_V18_FOLD5_PA_TRANSITION_FOLD4",
        package_sha256=MLB_OBJECT, cells=cells(raw["awayRuns"], raw["homeRuns"]), draw_count=raw["simulationCount"])
    p = probabilities(pop)
    require_close(p["home"], forecast["probabilities"]["homeWin"], "MLB home win")
    require_close(p["away"], forecast["probabilities"]["awayWin"], "MLB away win")
    require_close(p["tie"], 0.0, "MLB tie")
    rows.append({"sport": "MLB", "binding": pop.binding, "probabilities": p,
                 "source": physical(root / "execution-inputs.json"), "status": "VERIFIED_READ_ONLY"})

    root = exchange / "aisp-daily-forecast-bundles/sha256" / NFL_PACKAGE
    bundle_path = root / "bundle.json"
    bundle = read_json(bundle_path)
    forecast = next(value for value in bundle["forecasts"] if value["eventId"] == "2026_02_IND_KC")
    n = forecast["simulator"]["completedSimulations"]
    joint = [{"awayScore": row["awayScore"], "homeScore": row["homeScore"], "count": round(row["probability"] * n)}
             for row in forecast["jointScoreDistribution"]]
    pop = JointScorePopulation.from_cells(
        sport="NFL", game_id=forecast["eventId"], forecast_id=forecast["forecastId"],
        model_id=forecast["engine"]["engineId"], configuration_id=forecast["engine"]["engineVersion"],
        package_sha256=NFL_PACKAGE, cells=joint, draw_count=n)
    p = probabilities(pop)
    for field, expected in (("home", forecast["homeWinProbability"]), ("away", forecast["awayWinProbability"]), ("tie", forecast["tieProbability"])):
        require_close(p[field], expected, f"NFL {field}")
    rows.append({"sport": "NFL", "binding": pop.binding, "probabilities": p,
                 "source": physical(bundle_path), "status": "VERIFIED_READ_ONLY"})

    root = exchange / "nba-gen1-research-v1/joint-comparison-v1/packages/sha256" / NBA_PACKAGE
    forecast_path = root / "forecasts/baseline.json"
    forecast = read_json(forecast_path)
    frame = pd.read_parquet(root / "populations/baseline-joint-draws.parquet")
    pop = JointScorePopulation.from_cells(
        sport="NBA", game_id=forecast["game"]["game_id"], forecast_id=forecast["forecastId"],
        model_id="NBA_GEN1_JOINT_BASELINE", configuration_id=forecast["configurationIdentity"],
        package_sha256=NBA_PACKAGE, cells=cells(frame["awayBOS"], frame["homeDET"]),
        draw_count=forecast["jointSimulation"]["drawCount"])
    p = probabilities(pop)
    expected = forecast["jointSimulation"]["winnerProbabilities"]
    for field, source_field in (("home", "homeDET"), ("away", "awayBOS"), ("tie", "tie")):
        require_close(p[field], expected[source_field], f"NBA {field}")
    rows.append({"sport": "NBA", "binding": pop.binding, "probabilities": p,
                 "source": physical(forecast_path), "populationFile": physical(root / "populations/baseline-joint-draws.parquet"),
                 "status": "VERIFIED_READ_ONLY"})

    root = exchange / "cfb-gen1-research-v1/current-v1/packages/sha256" / CFB_PACKAGE
    forecast_path = root / "forecast.json"
    forecast = read_json(forecast_path)
    frame = pd.read_parquet(root / "baseline-joint-draws.parquet")
    pop = JointScorePopulation.from_cells(
        sport="CFB", game_id=f"cfbd:{forecast['game']['game_id']}", forecast_id=forecast["forecastId"],
        model_id="CFB_GEN1_RIDGE_A100", configuration_id=forecast["baseline"]["configuration"],
        package_sha256=CFB_PACKAGE, cells=cells(frame["away_score"], frame["home_score"]),
        draw_count=forecast["baseline"]["drawCount"])
    p = probabilities(pop)
    require_close(p["home"], forecast["baseline"]["jointHomeWinProbability"], "CFB home")
    require_close(p["tie"], 0.0, "CFB tie")
    rows.append({"sport": "CFB", "binding": pop.binding, "probabilities": p,
                 "source": physical(forecast_path), "populationFile": physical(root / "baseline-joint-draws.parquet"),
                 "status": "VERIFIED_READ_ONLY"})

    return {"schemaVersion": "ASP_MARKET_PROBABILITY_SOURCE_AUDIT_V1", "sports": rows,
            "accounting": {"providerCalls": 0, "providerBytes": 0, "modelRuns": 0, "aispWrites": 0,
                           "exchangeWrites": 0, "outcomeReads": 0, "sealedPayloadReads": 0}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--studio", type=Path, required=True)
    parser.add_argument("--exchange", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.studio, args.exchange), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
