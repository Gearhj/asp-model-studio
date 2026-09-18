"""Frozen Gen1 rendering for the slate publisher; no fitting or acquisition."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import uuid

import numpy as np
import pandas as pd

from .authority import reference, verified_bytes
from .joint_residual import DRAW_COUNT, ENGINE, MASTER_SEED, eligible_bank, seed, simulate_pair
from .point_forecast import build_point_forecast
from .production import assemble_forecast, canonical_bytes, digest, verify_forecast
from .slate_lifecycle import immutable, now, read_ref, utc


def render(row, bundle_ref, release_ref, key, build_root):
    bundle, release = read_ref(bundle_ref), read_ref(release_ref)
    build = Path(build_root) / uuid.uuid4().hex
    build.mkdir(parents=True)
    target = row["target"]
    schedule = {"schema": "NBA_GEN1_REDUCED_SCHEDULE_EVIDENCE_V1",
        "dataClassification": "REAL_UNSCRAMBLED_GAMES", "reviewedBy": bundle["reviewedBy"],
        "capturedAtUtc": bundle["scheduleCapturedAtUtc"], "sourceObject": bundle["source"],
        "rightsEvidence": bundle["rightsEvidence"], "target": target,
        "sourceRevisionIsHistoricalPublicationClock": False, "inputVersion": bundle_ref}
    schedule_ref = immutable(build / "evidence/schedule.json", canonical_bytes(schedule))
    coverage = copy.deepcopy(read_ref(bundle["coverageTemplate"]))
    coverage.update(targetGameId=target["game_id"], teamIds=[target["home_team_id"], target["away_team_id"]])
    coverage_ref = immutable(build / "evidence/history-coverage.json", canonical_bytes(coverage))
    point = build_point_forecast(bundle["currentModelReceipt"], schedule_ref, coverage_ref, bundle["sourceCutoffUtc"])
    immutable(build / "evidence/point-forecast.json", canonical_bytes(point))
    method = read_ref(release["jointMethod"])
    if method["engine"] != ENGINE or method["masterSeed"] != MASTER_SEED or method["drawCountPerGamePerArm"] != DRAW_COUNT:
        raise ValueError("Frozen joint method changed")
    verified_bytes(method["residuals"])
    residuals = pd.read_parquet(method["residuals"]["path"])
    bank = eligible_bank(residuals, target["game_date"], target["game_id"])
    simulations, center = simulate_pair(np.array([point["pointExpectations"]["home"], point["pointExpectations"]["away"]]),
        bank[["residual_home", "residual_away"]].to_numpy(), target["game_id"])
    draws = simulations["paired"]["draws"].astype(np.int64)
    path = build / "population/joint-final-score-draws.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame({"drawIndex": np.arange(DRAW_COUNT, dtype=np.int32),
        "homeScore": draws[:, 0].astype(np.int16), "awayScore": draws[:, 1].astype(np.int16),
        "homeTeamCode": target["home_team_code"], "awayTeamCode": target["away_team_code"]}).to_parquet(path, index=False, compression="zstd")
    ref = reference(path)
    population = {"artifact": {"relativePath": "population/joint-final-score-draws.parquet", "sha256": ref["sha256"], "bytes": ref["bytes"]},
        "logicalHomeAwayInt64LeSha256": digest(draws.astype("<i8").tobytes()), "drawCount": DRAW_COUNT,
        "orientation": "HOME_AWAY", "paired": True, "fullTailRetained": True}
    current = read_ref(bundle["currentModelReceipt"])
    bindings = {"pointModel": current["models"]["ridge_a100_rest"]["artifact"],
        "eloModel": current["models"]["elo"]["artifact"], "currentModelReceipt": bundle["currentModelReceipt"],
        "featureContractSha256": point["bindings"]["featureContractSha256"],
        "pointTrainingIdentitySha256": point["bindings"]["pointTrainingIdentitySha256"],
        "scheduleEvidence": schedule_ref, "historyCoverage": coverage_ref,
        "jointMethod": release["jointMethod"], "residualPopulation": method["residuals"],
        "deploymentManifest": release["deploymentManifest"], "slateRelease": release_ref,
        "inputVersion": bundle_ref, "revisionKey": key}
    created = now()
    forecast = assemble_forecast(point_forecast=point, draws=draws, created_at_utc=created,
        effective_at_utc=release["prospectiveEffectiveAtUtc"], handoff=release["modelHandoff"],
        bindings=bindings, population=population)
    # Assembly is private preparation. The durable commit receipt is the actual
    # publication clock. A crash must never backdate availability to preparation.
    immutable(build / "forecast.json", canonical_bytes(forecast))
    donors = np.random.default_rng(seed(target["game_id"], "paired-donors")).integers(len(bank), size=DRAW_COUNT)
    immutable(build / "evidence/simulation-receipt.json", canonical_bytes({
        "schema": "NBA_GEN1_PRODUCTION_SIMULATION_RECEIPT_V1", "createdAtUtc": created,
        "gameId": target["game_id"], "engine": ENGINE, "drawCount": DRAW_COUNT, "masterSeed": MASTER_SEED,
        "residualPopulation": method["residuals"], "eligibleResidualDonors": len(bank),
        "residualBankColumnCenter": center.tolist(), "donorIndexInt64LeSha256": digest(donors.astype("<i8").tobytes()),
        "drawsDiscarded": 0, "finalTies": 0, "closeScoreChallengerApplied": False,
        "modelFits": 0, "providerCalls": 0, "targetOutcomesAccessed": False}))
    files = [{"relativePath": p.relative_to(build).as_posix(), **{k: v for k, v in reference(p).items() if k != "path"}}
             for p in sorted(build.rglob("*")) if p.is_file()]
    index = {"schemaVersion": "NBA_GEN1_PRODUCTION_FORECAST_PACKAGE_INDEX_V2", "createdAtUtc": created,
        "publishedAtUtc": None, "publicationClockAuthority": "Bound discovery entry committedAtUtc; never package creation",
        "forecastId": forecast["forecastId"], "game": target, "revisionKey": key,
        "configurationIdentity": forecast["configurationIdentity"], "distributionConfigurationIdentity": ENGINE,
        "drawCount": DRAW_COUNT, "population": population, "forecastSha256": reference(build / "forecast.json")["sha256"],
        "inputVersion": bundle_ref, "productionHandoff": release_ref, "files": files, "consumerAcknowledged": False}
    immutable(build / "index.json", canonical_bytes(index))
    verify_package(build)
    return build


def verify_package(package):
    package = Path(package)
    index = json.loads((package / "index.json").read_bytes())
    if index["schemaVersion"] != "NBA_GEN1_PRODUCTION_FORECAST_PACKAGE_INDEX_V2":
        raise ValueError("Wrong slate package schema")
    if len(package.name) == 64 and digest((package / "index.json").read_bytes()) != package.name:
        raise ValueError("Package address mismatch")
    seen = set()
    for row in index["files"]:
        rel = Path(row["relativePath"])
        if rel.is_absolute() or ".." in rel.parts or row["relativePath"] in seen:
            raise ValueError("Unsafe/duplicate member path")
        seen.add(row["relativePath"])
        verified_bytes({"path": str(package / rel), "sha256": row["sha256"], "bytes": row["bytes"]})
    forecast = json.loads((package / "forecast.json").read_bytes())
    if reference(package / "forecast.json")["sha256"] != index["forecastSha256"] or forecast["forecastId"] != index["forecastId"]:
        raise ValueError("Forecast/index binding mismatch")
    pop = pd.read_parquet(package / index["population"]["artifact"]["relativePath"])
    draws = pop[["homeScore", "awayScore"]].to_numpy(dtype=np.int64)
    if list(pop.drawIndex) != list(range(DRAW_COUNT)) or set(pop.homeTeamCode) != {forecast["game"]["home_team_code"]} or set(pop.awayTeamCode) != {forecast["game"]["away_team_code"]}:
        raise ValueError("Draw identity/orientation mismatch")
    if digest(draws.astype("<i8").tobytes()) != index["population"]["logicalHomeAwayInt64LeSha256"]:
        raise ValueError("Population binding mismatch")
    if not utc(forecast["sourceCutoffUtc"]) <= utc(forecast["createdAtUtc"]) < utc(forecast["game"]["scheduled_tipoff_utc"]):
        raise ValueError("Forecast chronology mismatch")
    verify_forecast(forecast, draws)
    return index
