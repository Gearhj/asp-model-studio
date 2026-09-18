"""Issue one immutable prospective NBA Gen1 production-baseline forecast.

This uses only retained pregame schedule/history evidence.  It never acquires
data, fits a model, enables a scheduler, or writes AISP.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.sports_nba_gen1.authority import reference, verified_bytes
from server.sports_nba_gen1.current_history_source import TEAM_IDENTITIES, _team
from server.sports_nba_gen1.joint_residual import DRAW_COUNT, ENGINE, MASTER_SEED, eligible_bank, seed, simulate_pair
from server.sports_nba_gen1.point_forecast import build_point_forecast
from server.sports_nba_gen1.production import assemble_forecast, canonical_bytes, digest, verify_forecast


LEGACY_RESEARCH_GAMES = {401909088}
SCHEDULE_SHA = "d4ffe0d974dbec227af1ea5d731e0f36426839a170bfd0bbffc39b65f933a090"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_once(path: Path, raw: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise RuntimeError(f"immutable conflict: {path}")
    else:
        path.write_bytes(raw)
    return reference(path)


def _target_evidence(data_root: Path, build: Path, game_id: int) -> tuple[dict, dict, str]:
    if game_id in LEGACY_RESEARCH_GAMES:
        raise RuntimeError("Legacy BOS-DET research identity cannot be relabelled or reissued by production")
    base = data_root / "nba-gen1-long-gap-v1"
    capture = json.loads((base / "future-schedule-capture.json").read_bytes())
    source = capture["source"]
    if source["sha256"] != SCHEDULE_SHA:
        raise RuntimeError("Governed schedule source changed")
    verified_bytes(source)
    frame = pd.read_parquet(source["path"])
    row = frame[frame.id.astype(int) == game_id]
    if len(row) != 1:
        raise RuntimeError("Requested schedule identity is absent or duplicated")
    item = row.iloc[0].to_dict()
    if (int(item["season"]) != 2027 or int(item["season_type"]) != 2
            or int(item["type_id"]) != 1 or item["type_abbreviation"] != "STD"
            or bool(item["neutral_site"]) or bool(item["status_type_completed"])
            or item["status_type_state"] != "pre"):
        raise RuntimeError("Requested game is not an eligible regular-season pregame target")
    if int(item["home_id"]) not in TEAM_IDENTITIES or int(item["away_id"]) not in TEAM_IDENTITIES:
        raise RuntimeError("Unmapped schedule team")
    home, away = _team(item, "home"), _team(item, "away")
    tipoff = pd.to_datetime(item["date"], utc=True)
    if pd.Timestamp.now(tz="UTC") >= tipoff:
        raise RuntimeError("Target already started")
    target = {"game_id": f"nba-espn:game:{game_id}", "source_game_id": game_id,
        "season_end": 2027, "game_date": str(item["game_date"]),
        "home_team_id": f"nba-neil:franchise:{home}", "away_team_id": f"nba-neil:franchise:{away}",
        "home_team_code": home, "away_team_code": away, "neutral_site": False,
        "scheduled_tipoff_utc": tipoff.isoformat(), "season_type": "REGULAR", "status": "SCHEDULED",
        "source_revision": "github-asset:552084615:sha256:" + SCHEDULE_SHA}
    if tipoff.tz_convert("America/New_York").date().isoformat() != target["game_date"]:
        raise RuntimeError("Eastern game date/tipoff mismatch")
    original_schedule = json.loads((base / "future-schedule-evidence-qualified.json").read_bytes())
    cutoff = capture["capturedAtUtc"]
    evidence = {"schema": "NBA_GEN1_REDUCED_SCHEDULE_EVIDENCE_V1",
        "dataClassification": "REAL_UNSCRAMBLED_GAMES", "reviewedBy": "NBA Gen1 production readiness",
        "capturedAtUtc": cutoff, "sourceObject": source, "rightsEvidence": original_schedule["rightsEvidence"],
        "target": target,
        "selectionRule": "Explicit first production-path target: earliest authenticated opening-night game after the excluded BOS-DET legacy research identity.",
        "metadataProjection": capture["metadata"], "sourceRevisionIsHistoricalPublicationClock": False,
        "networkRequests": 0, "outcomeColumnsRead": []}
    schedule_path = build / "evidence/schedule-evidence.json"
    write_once(schedule_path, canonical_bytes(evidence))
    current_path = base / "current-research/receipt.json"
    current_ref = reference(current_path)
    prior_coverage = json.loads((base / "current-history-coverage.json").read_bytes())
    coverage = dict(prior_coverage)
    coverage.update({"createdAtUtc": utcnow(), "currentResearchReceiptSha256": current_ref["sha256"],
        "targetGameId": target["game_id"], "teamIds": [target["home_team_id"], target["away_team_id"]],
        "sourceCutoffUtc": cutoff, "completeThroughUtc": cutoff, "networkRequests": 0,
        "forecastGenerated": True})
    coverage["membershipReview"] = dict(prior_coverage["membershipReview"],
        completed2026GamesPerTargetTeam={home: 82, away: 82})
    coverage["evidence"] = list(prior_coverage["evidence"]) + [reference(schedule_path)]
    coverage_path = build / "evidence/history-coverage.json"
    write_once(coverage_path, canonical_bytes(coverage))
    return reference(schedule_path), reference(coverage_path), cutoff


def _parquet(draws: np.ndarray, path: Path, home: str, away: str) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"drawIndex": np.arange(DRAW_COUNT, dtype=np.int32),
                  "homeScore": draws[:, 0].astype(np.int16),
                  "awayScore": draws[:, 1].astype(np.int16),
                  "homeTeamCode": home, "awayTeamCode": away}).to_parquet(path, index=False, compression="zstd")
    return reference(path)


def build_and_publish(args: argparse.Namespace) -> dict:
    data_root, exchange = Path(args.data_root), Path(args.exchange_root)
    output = Path(args.output_root) / f"espn-{args.game_id}"
    final_receipt = output / "publication-receipt.json"
    if final_receipt.exists():
        saved = json.loads(final_receipt.read_bytes())
        package = Path(saved["packageDirectory"])
        verify_package(package)
        return dict(saved, disposition="REUSED_IMMUTABLE")
    build = output / "build"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    schedule_ref, coverage_ref, cutoff = _target_evidence(data_root, build, args.game_id)
    current_ref = reference(data_root / "nba-gen1-long-gap-v1/current-research/receipt.json")
    point = build_point_forecast(current_ref, schedule_ref, coverage_ref, cutoff)
    method_path = data_root / "nba-gen1-joint-residual-v1/method-freeze.json"
    method = json.loads(method_path.read_bytes())
    if method["engine"] != ENGINE or method["masterSeed"] != MASTER_SEED or method["drawCountPerGamePerArm"] != DRAW_COUNT:
        raise RuntimeError("Joint method identity changed")
    residuals = pd.read_parquet(method["residuals"]["path"])
    bank = eligible_bank(residuals, point["game"]["game_date"], point["game"]["game_id"])
    expected = np.array([point["pointExpectations"]["home"], point["pointExpectations"]["away"]])
    simulations, center = simulate_pair(expected, bank[["residual_home", "residual_away"]].to_numpy(), point["game"]["game_id"])
    draws = simulations["paired"]["draws"].astype(np.int64)
    population_path = build / "population/joint-final-score-draws.parquet"
    population_ref = _parquet(draws, population_path, point["game"]["home_team_code"], point["game"]["away_team_code"])
    logical_sha = digest(draws.astype("<i8").tobytes())
    population = {"artifact": {"relativePath": "population/joint-final-score-draws.parquet",
        "sha256": population_ref["sha256"], "bytes": population_ref["bytes"]},
        "logicalHomeAwayInt64LeSha256": logical_sha, "drawCount": DRAW_COUNT,
        "orientation": "HOME_AWAY", "paired": True, "fullTailRetained": True}
    deployment = reference(args.deployment_manifest)
    handoff = reference(args.handoff_index)
    bindings = {"pointModel": json.loads(Path(current_ref["path"]).read_bytes())["models"]["ridge_a100_rest"]["artifact"],
        "eloModel": json.loads(Path(current_ref["path"]).read_bytes())["models"]["elo"]["artifact"],
        "currentModelReceipt": current_ref, "featureContractSha256": point["bindings"]["featureContractSha256"],
        "pointTrainingIdentitySha256": point["bindings"]["pointTrainingIdentitySha256"],
        "scheduleEvidence": schedule_ref, "historyCoverage": coverage_ref,
        "jointMethod": reference(method_path), "residualPopulation": method["residuals"],
        "deploymentManifest": deployment, "publisherExecutable": reference(Path(__file__))}
    created = utcnow()
    forecast = assemble_forecast(point_forecast=point, draws=draws, created_at_utc=created,
        effective_at_utc=args.effective_at_utc, handoff=handoff, bindings=bindings, population=population)
    publication = utcnow()
    forecast["publishedAtUtc"] = publication
    forecast_path = build / "forecast.json"
    write_once(forecast_path, canonical_bytes(forecast))
    donor_indices = np.random.default_rng(seed(point["game"]["game_id"], "paired-donors")).integers(len(bank), size=DRAW_COUNT)
    sim_receipt = {"schema": "NBA_GEN1_PRODUCTION_SIMULATION_RECEIPT_V1", "createdAtUtc": created,
        "gameId": point["game"]["game_id"], "sourceCutoffUtc": cutoff, "drawCount": DRAW_COUNT,
        "engine": ENGINE, "masterSeed": MASTER_SEED, "eligibleResidualDonors": len(bank),
        "residualLatestDate": str(bank.game_date.max()), "residualBankColumnCenter": center.tolist(),
        "donorIndexInt64LeSha256": digest(donor_indices.astype("<i8").tobytes()),
        "populationLogicalSha256": logical_sha, "drawsDiscarded": 0,
        "finalTies": int((draws[:, 0] == draws[:, 1]).sum()), "closeScoreChallengerApplied": False,
        "networkRequests": 0, "outcomesAccessed": False, "modelFits": 0}
    write_once(build / "evidence/simulation-receipt.json", canonical_bytes(sim_receipt))
    verify_forecast(forecast, draws)
    files = []
    for path in sorted(p for p in build.rglob("*") if p.is_file()):
        bound = reference(path)
        files.append({"relativePath": path.relative_to(build).as_posix(), "sha256": bound["sha256"], "bytes": bound["bytes"]})
    index = {"schemaVersion": "NBA_GEN1_PRODUCTION_FORECAST_PACKAGE_INDEX_V1", "createdAtUtc": created,
        "publishedAtUtc": publication, "forecastId": forecast["forecastId"], "game": forecast["game"],
        "configurationIdentity": forecast["configurationIdentity"],
        "distributionConfigurationIdentity": ENGINE, "drawCount": DRAW_COUNT,
        "forecastSha256": reference(forecast_path)["sha256"], "population": population,
        "productionHandoff": handoff, "files": files, "consumerAcknowledged": False,
        "idempotency": {"key": ["forecastId", "forecastSha256"], "sameBytes": "REUSE", "conflict": "REJECT"}}
    index_raw = canonical_bytes(index)
    address = digest(index_raw)
    package = exchange / "nba-gen1-production-v1/forecasts/sha256" / address
    package.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="nba-prod-", dir=package.parent))
    try:
        for path in sorted(p for p in build.rglob("*") if p.is_file()):
            target = temp / path.relative_to(build)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        (temp / "index.json").write_bytes(index_raw)
        verify_package(temp)
        if package.exists():
            verify_package(package)
            shutil.rmtree(temp)
        else:
            os.replace(temp, package)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    discovery = exchange / "nba-gen1-production-v1/discovery/current.json"
    discovery.parent.mkdir(parents=True, exist_ok=True)
    pointer = {"schemaVersion": "NBA_GEN1_PRODUCTION_DISCOVERY_V1", "updatedAtUtc": publication,
        "packages": [{"gameId": forecast["game"]["game_id"], "forecastId": forecast["forecastId"],
            "packageAddress": address, "index": reference(package / "index.json")}],
        "consumerAcknowledged": False}
    temp_pointer = discovery.with_suffix(".tmp")
    temp_pointer.write_bytes(canonical_bytes(pointer))
    os.replace(temp_pointer, discovery)
    receipt = {"schema": "NBA_GEN1_PRODUCTION_PUBLICATION_RECEIPT_V1", "publishedAtUtc": publication,
        "disposition": "PUBLISHED_NEW_PROSPECTIVE", "gameId": forecast["game"]["game_id"],
        "forecastId": forecast["forecastId"], "forecast": reference(package / "forecast.json"),
        "packageAddress": address, "packageDirectory": str(package), "index": reference(package / "index.json"),
        "discovery": reference(discovery), "providerCalls": 0, "providerBytes": 0, "costUsd": 0,
        "aispWrites": 0, "consumerAcknowledged": False}
    write_once(final_receipt, canonical_bytes(receipt))
    return receipt


def verify_package(package: Path) -> dict:
    raw = (package / "index.json").read_bytes()
    index = json.loads(raw)
    if digest(raw) != package.name:
        raise RuntimeError("Package address/index digest mismatch")
    for item in index["files"]:
        child = package / item["relativePath"]
        if not child.is_file() or reference(child)["sha256"] != item["sha256"] or child.stat().st_size != item["bytes"]:
            raise RuntimeError("Package member mismatch: " + item["relativePath"])
    pop = pd.read_parquet(package / index["population"]["artifact"]["relativePath"])
    draws = pop[["homeScore", "awayScore"]].to_numpy(dtype=np.int64)
    if digest(draws.astype("<i8").tobytes()) != index["population"]["logicalHomeAwayInt64LeSha256"]:
        raise RuntimeError("Logical population mismatch")
    forecast = json.loads((package / "forecast.json").read_bytes())
    verify_forecast(forecast, draws)
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-id", type=int, default=401909089)
    parser.add_argument("--data-root", default=r"C:\Users\james\asp-model-studio\outputs")
    parser.add_argument("--output-root", default=r"C:\Users\james\asp-model-studio\outputs\nba-gen1-production-v1")
    parser.add_argument("--exchange-root", default=r"C:\Users\james\asp-model-exchange")
    parser.add_argument("--handoff-index", required=True)
    parser.add_argument("--deployment-manifest", required=True)
    parser.add_argument("--effective-at-utc", required=True)
    args = parser.parse_args()
    print(json.dumps(build_and_publish(args), indent=2))


if __name__ == "__main__":
    main()
