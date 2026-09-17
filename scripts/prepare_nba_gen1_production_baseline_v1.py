"""Stage the existing NBA Gen1 baseline for production activation.

This verifies immutable external artifacts and writes a content-addressed
producer handoff. It does not alter AISP, install a task, run a forecast, or
grant wagering authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def reference(path: str | Path, expected: str | None = None) -> dict:
    p = Path(path).resolve()
    raw = p.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if expected and sha != expected:
        raise RuntimeError(f"digest mismatch: {p}")
    return {"path": str(p), "sha256": sha, "bytes": len(raw)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--data-root", default=r"C:\Users\james\asp-model-studio\outputs")
    parser.add_argument("--exchange-root", default=r"C:\Users\james\asp-model-exchange")
    args = parser.parse_args()
    data = Path(args.data_root)
    exchange = Path(args.exchange_root)
    source_receipt = reference(data / "nba-gen1-long-gap-v1/current-research/receipt.json")
    source = json.loads(Path(source_receipt["path"]).read_bytes())
    ridge = reference(source["models"]["ridge_a100_rest"]["artifact"]["path"], "063e69ffb685a16bd784276fa94bce27f8e2d5e91f744e8c9a60a46f242f70ef")
    elo = reference(source["models"]["elo"]["artifact"]["path"], "6a1391e7e0f321b722a284292499055323eeea7e238f60eb51c53042487b11fe")
    point_index = reference(exchange / "nba-gen1-research-v1/point-elo-v1/packages/sha256/85e3d7414ccaac4b79c524096af3f7fa894169041e143ee3dc5894002f53e2e0/index.json", "85e3d7414ccaac4b79c524096af3f7fa894169041e143ee3dc5894002f53e2e0")
    point_forecast = reference(exchange / "nba-gen1-research-v1/point-elo-v1/packages/sha256/85e3d7414ccaac4b79c524096af3f7fa894169041e143ee3dc5894002f53e2e0/forecast.json", "27f766e341cc211317d61e7ed842d7bbff7521664da5b27a0776bfc5394a8767")
    joint_index = reference(exchange / "nba-gen1-research-v1/joint-comparison-v1/packages/sha256/00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d/index.json", "00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d")
    joint_forecast = reference(exchange / "nba-gen1-research-v1/joint-comparison-v1/packages/sha256/00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d/forecasts/baseline.json", "2fb6a1c382a3eda10633a067863745ecb8fbd3b6eec2f31659c9a583d8774d99")
    joint_population = reference(exchange / "nba-gen1-research-v1/joint-comparison-v1/packages/sha256/00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d/populations/baseline-joint-draws.parquet", "9e8b7be8b7081fb355812889ca991095fca2571877d712853e26443d2b57eb01")
    manifest = {
        "schemaVersion": "NBA_GEN1_PRODUCTION_BASELINE_V1",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "status": "STAGED_INACTIVE",
        "selectionReason": "NBA Gen2 acquisition stopped at the declared source/schema integrity gate; the exact completed Gen1 baseline is the required fallback.",
        "configurationIdentity": "NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1",
        "pointModel": {"expectedScores": "corrected Ridge alpha=100 ordinary-rest", "artifact": ridge},
        "winnerModel": {"probabilities": "chronological Elo, independent of Ridge and joint draws", "artifact": elo},
        "distributionModel": {"configurationIdentity": "NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1", "drawCount": 10000, "artifact": joint_forecast, "population": joint_population,
            "limitation": "Retained paired-residual distribution has excess one-point mass; close-score challenger is not enabled."},
        "history": {"games": source["historyGames"], "trainingGames": source["trainingGames"], "throughSeasonEnd": source["trainingThroughSeasonEnd"], "latestGameDate": source["latestRecordedGameDate"], "evidenceClass": "A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION", "receipt": source_receipt},
        "reusedHistoricalAssessment": {
            "point": {"season2024": {"games": 1225, "scoreMae": 9.31, "marginMae": 11.07, "totalMae": 14.78, "eloLogLoss": 0.616, "eloBrier": 0.214, "eloAuc": 0.714}, "season2025": {"games": 1221, "scoreMae": 9.28, "marginMae": 10.95, "totalMae": 14.90, "eloLogLoss": 0.617, "eloBrier": 0.214, "eloAuc": 0.716}},
            "joint": {"games": 7009, "energyScore": 10.434157, "totalCrps": 10.755059, "marginCrps": 7.873538, "winnerLogLoss": 0.625271, "winnerBrier": 0.217916, "onePointMass": 0.0778, "observedOnePointRate": 0.0401}
        },
        "existingResearchForecasts": {"pointPackage": point_index, "pointForecast": point_forecast, "jointPackage": joint_index, "note": "Immutable research forecasts remain research; activation must create separately identified prospective production revisions."},
        "authority": {"productionLabelAllowedAfterExplicitActivation": True, "currentlyActive": False, "schedulerInstalled": False, "wageringAuthority": False, "decisionAuthority": False, "positionAuthority": False},
        "unsupportedInputs": ["pregame injuries", "lineups", "projected minutes", "player strength", "referees", "travel", "team-box possession features"],
        "activationGate": "Separate authorization must install one canonical scheduler, publish a new eligible forecast after its source cutoff, and pin AISP to this exact handoff. Existing research forecasts cannot be relabelled.",
    }
    out = Path(args.output).resolve()
    stage = out / "staging"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    (stage / "manifest.json").write_bytes(json_bytes(manifest))
    handoff = f"""# Claude/AISP handoff — NBA Gen1 production baseline\n\nStatus: **STAGED_INACTIVE**. Configuration `NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1` is the selected fallback because Gen2 data admission stopped fail-closed. Ridge supplies expected scores; Elo supplies winner probabilities independently. The paired OOF residual population supplies 10,000 joint final-score draws and totals, with the disclosed excess one-point-margin mass. The close-score challenger is disabled.\n\nDo not import or relabel the existing BOS–DET research forecasts as production. After separate activation authority, consume a newly generated prospective package bound to this handoff and preserve its source, creation and publication clocks. No wagering, decision, position or scheduler authority is granted by this package.\n\nThe consumer must display missing player/lineup/injury/team-box information and keep Elo probabilities distinct from joint-population winner probabilities.\n"""
    (stage / "CLAUDE_HANDOFF.md").write_text(handoff, encoding="utf-8", newline="\n")
    scheduler = {"schemaVersion": "NBA_PRODUCTION_SCHEDULER_STAGING_V1", "status": "NOT_INSTALLED", "canonicalTaskName": "ASP NBA Forecast Publisher", "ownerCount": 0,
        "entrypoint": "scripts/forecast_nba_gen1_point.py followed by scripts/publish_nba_gen1_joint_prospective.py through a future bounded owner wrapper",
        "prospectiveCaptureHook": "After each governed FINAL, retain the latest authorized schedule/result revision and team-box response; update features only for later targets.",
        "activation": "Requires separate authorization and a supported installer/deployment identity; do not register a task from this staging descriptor."}
    (stage / "SCHEDULER_STAGING.json").write_bytes(json_bytes(scheduler))
    members = []
    for name in ("manifest.json", "CLAUDE_HANDOFF.md", "SCHEDULER_STAGING.json"):
        bound = reference(stage / name)
        members.append({"relativePath": name, "sha256": bound["sha256"], "bytes": bound["bytes"]})
    index = {"schemaVersion": "NBA_PRODUCTION_BASELINE_HANDOFF_INDEX_V1", "members": members}
    index_raw = json_bytes(index)
    address = hashlib.sha256(index_raw).hexdigest()
    package = out / "packages" / "sha256" / address
    if package.exists():
        shutil.rmtree(package)
    shutil.copytree(stage, package)
    (package / "index.json").write_bytes(index_raw)
    shutil.rmtree(stage)
    current = {"packageAddress": address, "index": reference(package / "index.json"), "status": "STAGED_INACTIVE"}
    (out / "current.json").write_bytes(json_bytes(current))
    print(json.dumps(current, indent=2))


if __name__ == "__main__":
    main()
