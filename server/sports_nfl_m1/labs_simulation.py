"""Immutable, exact-distribution NFL Labs supplements; never changes a forecast.

The operational M1 already persists its empirical *joint* distribution.  Exporting
that measure is both more faithful and cheaper than inventing another simulator.
The empirical multiset is recoverable, but the original draw order is not asserted.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_gold.nfl_shadow_exchange import (
    BUNDLE_OBJECT_FAMILY, NFL_2026_RESEARCH_SHADOW_INDEX_NAME,
    _strict_json, _validate_nfl_2026_locator, verify_sports_forecast_bundle,
)
from .current_shadow import _effective_forecasts

CONTRACT = "NFL_LABS_CONTRACT_V1"
SUPPLEMENT = "NFL_LABS_SCORE_DISTRIBUTION_V1"
FAMILY = "nfl-labs-simulation-supplements"
AUTHORITY = dict(status="RESEARCH_SHADOW", promotionStatus="NOT_PROMOTED",
                 wageringAuthority=False, executionAllowedInAISP=False)


class PregameClosed(ValueError):
    pass


def pregame_clock(kickoff: str, *, clock: Callable[[], datetime], stage: str) -> datetime:
    observed = utc(clock())
    if observed >= utc(kickoff):
        raise PregameClosed(f"KICKOFF_REACHED_BEFORE_{stage}")
    return observed


def utc(value: str | datetime) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return result.astimezone(timezone.utc)


def file_record(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(payload).hexdigest(), "byteCount": len(payload)}


def registered_source_availability(bronze_root: Path, fit_receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve timestamp provenance from registered metadata, not game outcomes."""
    pointer = json.loads((bronze_root / "current.json").read_bytes())
    manifest_path = bronze_root / pointer["manifestRelativePath"]
    manifest_ref = file_record(manifest_path)
    if manifest_ref["sha256"] != pointer["manifestSha256"]:
        raise ValueError("registered bronze manifest checksum differs")
    manifest = json.loads(manifest_path.read_bytes())
    expected = {item["sha256"] for item in fit_receipt["sourceEvidence"]["sources"]}
    records = [item for item in manifest["partitions"] if item["fileSha256"] in expected]
    if {item["fileSha256"] for item in records} != expected:
        raise ValueError("fitted source objects do not all have registered availability metadata")
    assets = []
    for item in records:
        if item["familyId"] != "play_by_play" or item["season"] not in range(2018, 2025):
            raise ValueError("drive source metadata is not Development PBP2018--2024")
        retrieved = utc(item["retrievedAt"])
        assets.append({"season": item["season"], "fileSha256": item["fileSha256"],
                       "retrievedAtUtc": retrieved.isoformat(), "assetUpdatedAtUtc": item.get("assetUpdatedAt"),
                       "releasePublishedAtUtc": item.get("releasePublishedAt"), "sourceUrl": item.get("sourceUrl")})
    return {"status": "REGISTERED_LOCAL_RETRIEVAL_TIMESTAMPS_AVAILABLE", "registeredManifest": manifest_ref,
            "sourceCutoffUtc": max(utc(item["retrievedAtUtc"]) for item in assets).isoformat(),
            "cutoffMeaning": "LATEST_REGISTERED_LOCAL_RETRIEVAL_OF_THE_EXACT_FITTED_SOURCE_OBJECTS",
            "historicalEvidenceThroughDate": fit_receipt["trainingCutoff"],
            "historicalEvidenceSeason": 2024, "historicalEvidencePrecision": "GAME_DATE_NOT_COMPLETION_OR_RELEASE_TIMESTAMP",
            "assets": sorted(assets, key=lambda item: item["season"]),
            "limitations": "A recent archive retrieval does not mean team evidence is current; historical game information stops at the2024season. Release metadata is separate from game completion time."}


def immutable_json(path: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    payload = canonical_json_bytes(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"immutable object already exists with different bytes: {path}")
    else:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    return file_record(path)


def coordination_contract(exchange_root: Path) -> dict[str, Any]:
    return {
        "schemaVersion": CONTRACT, "owner": "ASP_MODEL_STUDIO", **AUTHORITY,
        "artifactVersions": {"scoreDistribution": SUPPLEMENT,
                             "driveSimulation": "NFL_LABS_DRIVE_SIMULATION_V1"},
        "discoveryPointerPath": str((exchange_root / FAMILY / "current.json").resolve()),
        "immutableObjectPattern": str((exchange_root / FAMILY / "sha256" / "{artifactSha256}" / "artifact.json").resolve()),
        "manifestFile": "manifest.json",
        "identityFields": ["forecastId", "eventId", "homeTeam", "awayTeam", "model", "sourceForecast"],
        "timingFields": ["scheduledStartUtc", "forecastCreatedUtc", "sourceCutoffUtc", "publishedAtUtc"],
        "distributionFields": ["drawCount", "seed", "jointScoreDistribution", "scoreMarginDistribution", "totalScoreDistribution", "scoreSummary", "quantiles", "representativeFinals"],
        "optionalFields": ["simulatedDrives", "scenario"],
        "rawVersusCalibrated": "A distribution and its derived probabilities must agree. Separately calibrated probabilities, when available, are labeled separately, not described as generated by the raw distribution.",
        "marketQuery": {"homeSpread": "homeScore - awayScore + line; >0 cover, =0 push", "total": "homeScore + awayScore - line; >0 over, =0 push", "moneylineTieVoid": "condition home/away probabilities on a non-tie; retain original three-way probabilities"},
        "importInstructions": "Read the separate current.json pointer; verify every artifact and manifest checksum/byte count; join forecastId/eventId/model identity. Render exact PMFs as distributions. Render drive replays only from a driveSimulation artifact and under its own engine identity. Never execute a model or treat these artifacts as wagering authority.",
        "legacyBundleRule": "Original forecast bundles keep their exact three-file inventory unchanged. This family is separate.",
    }


def empirical_scores(forecast: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    draws = int(forecast["simulator"]["simulationCount"])
    rows = forecast["jointScoreDistribution"]
    counts = np.asarray([round(float(row["probability"]) * draws) for row in rows], dtype=np.int64)
    if counts.sum() != draws or np.any(counts <= 0):
        raise ValueError("joint PMF is not the complete saved empirical population")
    if any(abs(count / draws - float(row["probability"])) > 1e-14 for count, row in zip(counts, rows, strict=True)):
        raise ValueError("joint PMF probability does not match an integer population count")
    home = np.repeat([int(row["homeScore"]) for row in rows], counts)
    away = np.repeat([int(row["awayScore"]) for row in rows], counts)
    if np.any(home < 0) or np.any(away < 0):
        raise ValueError("negative score")
    return home, away


def summarize_scores(home: np.ndarray, away: np.ndarray) -> dict[str, Any]:
    return {"expectedHomeScore": float(home.mean()), "expectedAwayScore": float(away.mean()),
            "expectedMarginHomeMinusAway": float((home-away).mean()), "expectedTotal": float((home+away).mean()),
            "homeWinProbability": float(np.mean(home > away)), "awayWinProbability": float(np.mean(home < away)),
            "tieProbability": float(np.mean(home == away))}


def market_query(home: np.ndarray, away: np.ndarray, *, home_spread: float, total_line: float) -> dict[str, float]:
    margin, total = home-away+home_spread, home+away-total_line
    return {"homeCoverProbability": float(np.mean(margin > 0)), "awayCoverProbability": float(np.mean(margin < 0)),
            "spreadPushProbability": float(np.mean(margin == 0)), "overProbability": float(np.mean(total > 0)),
            "underProbability": float(np.mean(total < 0)), "totalPushProbability": float(np.mean(total == 0))}


def score_supplement(forecast: Mapping[str, Any], *, bundle_path: Path, published_at: datetime) -> dict[str, Any]:
    if not (utc(forecast["sourceCutoffUtc"]) <= utc(forecast["forecastCutoffUtc"]) <= utc(forecast["availableAsOfUtc"]) < utc(forecast["scheduledStartUtc"])):
        raise ValueError("saved forecast was not available before kickoff")
    if published_at >= utc(forecast["scheduledStartUtc"]):
        raise ValueError("current distribution publication must precede kickoff")
    home, away = empirical_scores(forecast)
    summary = summarize_scores(home, away)
    errors = {key: abs(summary[key]-float(forecast[key])) for key in ("expectedHomeScore", "expectedAwayScore", "homeWinProbability", "awayWinProbability", "tieProbability")}
    if max(errors.values()) != 0:
        raise ValueError(f"saved distribution and forecast numerical mismatch: {errors}")
    for rows, values, field in ((forecast["scoreMarginDistribution"], home-away, "homeMinusAway"), (forecast["totalScoreDistribution"], home+away, "totalScore")):
        observed, counts = np.unique(values, return_counts=True)
        reconstructed = {int(value): float(count / len(home)) for value, count in zip(observed, counts, strict=True)}
        if reconstructed != {int(row[field]): float(row["probability"]) for row in rows}:
            raise ValueError("saved marginal distribution differs from joint measure")
    seed = int(forecast["simulator"]["seed"])
    representative_rng = np.random.default_rng(seed)
    indices = representative_rng.choice(len(home), size=12, replace=False)
    quantiles = {name: {str(q): float(np.quantile(values, q)) for q in (.05, .25, .5, .75, .95)} for name, values in (("homeScore", home), ("awayScore", away), ("marginHomeMinusAway", home-away), ("total", home+away))}
    return {
        "schemaVersion": SUPPLEMENT, **AUTHORITY, "sport": "NFL",
        "forecastId": forecast["forecastId"], "eventId": forecast["eventId"],
        "homeTeam": forecast["homeTeam"], "awayTeam": forecast["awayTeam"], "model": forecast["engine"],
        "sourceForecast": {**file_record(bundle_path), "forecastId": forecast["forecastId"]},
        "scheduledStartUtc": forecast["scheduledStartUtc"], "forecastCreatedUtc": forecast["availableAsOfUtc"],
        "sourceCutoffUtc": forecast["sourceCutoffUtc"], "forecastCutoffUtc": forecast["forecastCutoffUtc"],
        "publishedAtUtc": published_at.isoformat().replace("+00:00", "Z"),
        "drawCount": len(home), "seed": seed, "scenario": {"scenarioId": "BASE", "modelInputChange": False},
        "generatingLaw": {"id": forecast["simulator"]["simulatorVersion"], "representation": "EXACT_SAVED_EMPIRICAL_JOINT_PMF", "pairedResidualDependencePreserved": True, "populationReconstruction": "INTEGER_COUNTS_RECOVERED_EXACTLY; ORIGINAL_DRAW_ORDER_NOT_ASSERTED", "calibration": "RAW_DISTRIBUTION_ONLY"},
        "jointScoreDistribution": forecast["jointScoreDistribution"], "scoreMarginDistribution": forecast["scoreMarginDistribution"], "totalScoreDistribution": forecast["totalScoreDistribution"],
        "scoreSummary": summary, "quantiles": quantiles,
        "representativeFinals": [{"representativeId": f"empirical-multiset-{int(index)}", "homeScore": int(home[index]), "awayScore": int(away[index]), "selectionSeed": seed} for index in indices],
        "spreadCoverProbabilities": forecast["spreadCoverProbabilities"], "overUnderProbabilities": forecast["overUnderProbabilities"],
        "reconciliation": {"forecastValueMaxAbsoluteMismatch": max(errors.values()), "marginalDistributionsExact": True, "jointPopulationCount": len(home)},
        "simulatedDrives": None,
        "limitations": ["Empirical final-score residual law preserves score dependence but is not constrained to football scoring sequences; it can assign mass to rare or structurally unsupported scores. Existing forecasts are not altered.", "Overtime incidence, regulation ties and player/drive paths are not identified by this final-score model.", "Representative finals are samples from the exact saved measure, not reconstructed original simulation trajectories.", "No sportsbook quote is supplied; line probabilities are model-free threshold queries of this same measure."],
    }


def publish_object(record: Mapping[str, Any], root: Path) -> dict[str, Any]:
    digest = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    path = root / "sha256" / digest / "artifact.json"
    artifact = immutable_json(path, record)
    manifest = immutable_json(path.with_name("manifest.json"), {"schemaVersion": "NFL_LABS_ARTIFACT_MANIFEST_V1", **AUTHORITY, "artifactSchemaVersion": record["schemaVersion"], "files": [artifact]})
    return {"artifact": artifact, "manifest": manifest, "eventId": record["eventId"], "forecastId": record["forecastId"], "modelId": record["model"]["engineId"], "artifactSchemaVersion": record["schemaVersion"]}


def verify_object(reference: Mapping[str, Any]) -> dict[str, Any]:
    for field in ("artifact", "manifest"):
        if file_record(Path(reference[field]["path"])) != reference[field]:
            raise ValueError(f"{field} checksum or byte count differs")
    record = json.loads(Path(reference["artifact"]["path"]).read_bytes())
    manifest = json.loads(Path(reference["manifest"]["path"]).read_bytes())
    if manifest["files"] != [reference["artifact"]]:
        raise ValueError("manifest inventory differs")
    if Path(reference["artifact"]["path"]).parent.name != reference["artifact"]["sha256"]:
        raise ValueError("artifact address differs")
    if any(record.get(key) != value for key, value in AUTHORITY.items()):
        raise ValueError("research authority differs")
    return record


def publish_current_score_distributions(exchange_root: Path, output_root: Path, *, now: datetime | None = None, window_days: int = 7,
                                        clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = utc(now or clock())
    contract_path = exchange_root / "contracts" / f"{CONTRACT}.json"
    expected_contract = coordination_contract(exchange_root)
    if contract_path.exists():
        accepted = json.loads(contract_path.read_bytes())
        if accepted != expected_contract:
            raise ValueError("existing coordination contract differs; preserve it and request interface reconciliation")
    contract_ref = immutable_json(contract_path, expected_contract)
    # The locator is discovery, not artifact authority. Validate its strict schema
    # and address lists, then fully verify every selected bundle below. Revalidating
    # hundreds of unrelated historical forecast objects is not needed for this
    # bounded rolling-slate exporter; original bundle validation remains unchanged.
    locator_bytes = (exchange_root / BUNDLE_OBJECT_FAMILY / NFL_2026_RESEARCH_SHADOW_INDEX_NAME).read_bytes()
    locator = _validate_nfl_2026_locator(_strict_json(locator_bytes, "NFL Labs source locator"))
    if canonical_json_bytes(locator) != locator_bytes:
        raise ValueError("source locator is not canonical JSON")
    published, skips, parent_before = [], [], {}
    for digest in locator["currentBundleSha256s"]:
        path = exchange_root / BUNDLE_OBJECT_FAMILY / "sha256" / digest / "bundle.json"
        # Read only current 2026 forecast metadata, never training or outcome data.
        header = json.loads(path.read_bytes())
        if not any(now <= utc(row["scheduledStartUtc"]) < now+timedelta(days=window_days) for row in header["forecasts"]):
            continue
        source = verify_sports_forecast_bundle(exchange_root, digest)
        parent_before[str(path)] = file_record(path)
        for forecast in _effective_forecasts(source.record).values():
            kickoff = utc(forecast["scheduledStartUtc"])
            if kickoff <= now:
                skips.append({"eventId": forecast["eventId"], "reason": "ALREADY_STARTED_NOT_RETROACTIVELY_PUBLISHED"})
                continue
            if kickoff >= now+timedelta(days=window_days):
                continue
            # Reuse a complete prior supplement for the same frozen parent/forecast.
            prior_pointer = exchange_root / FAMILY / "current.json"
            reuse = None
            if prior_pointer.exists():
                for old in json.loads(prior_pointer.read_bytes()).get("artifacts", []):
                    if old["forecastId"] == forecast["forecastId"] and old["artifactSchemaVersion"] == SUPPLEMENT:
                        prior = verify_object(old)
                        if prior["sourceForecast"]["sha256"] == digest:
                            reuse = old
                            break
            try:
                event_now = pregame_clock(forecast["scheduledStartUtc"], clock=clock, stage="DISTRIBUTION_EXPORT")
                record = None if reuse else score_supplement(forecast, bundle_path=path, published_at=event_now)
                publication_now = pregame_clock(forecast["scheduledStartUtc"], clock=clock, stage="PUBLICATION")
                if record is not None:
                    record["publishedAtUtc"] = publication_now.isoformat().replace("+00:00", "Z")
                item = reuse or publish_object(record, exchange_root / FAMILY)
            except PregameClosed as exc:
                skips.append({"eventId": forecast["eventId"], "reason": str(exc)})
                continue
            verify_object(item)
            published.append(item)
    if len({item["eventId"] for item in published}) != len(published):
        raise ValueError("duplicate current event distribution")
    for path, before in parent_before.items():
        if file_record(Path(path)) != before:
            raise ValueError("source forecast object changed")
    receipt = {"schemaVersion": "NFL_LABS_CURRENT_SIMULATIONS_V1", **AUTHORITY,
               "publishedAtUtc": utc(clock()).isoformat().replace("+00:00", "Z"), "windowDays": window_days,
               "statusDetail": "COMPLETE" if published else "NO_CURRENT_ELIGIBLE_SAVED_FORECASTS",
               "coordinationContract": contract_ref, "forecastCount": len(published), "artifacts": published, "skips": skips,
               "sourceForecastObjectsUnchanged": True, "modelFitOccurred": False, "sealedOotAccessed": False}
    digest = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
    handoff = immutable_json(output_root / "sha256" / digest / "handoff.json", receipt)
    # A separate mutable discovery pointer changes only after all referenced objects verify.
    pointer = exchange_root / FAMILY / "current.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    temporary = pointer.with_suffix(f".{os.getpid()}.tmp")
    discovery = {**receipt, "artifacts": list(published), "handoff": handoff}
    if pointer.exists():
        previous = json.loads(pointer.read_bytes())
        active_events = {item["eventId"] for item in published}
        other_engines = [item for item in previous.get("artifacts", [])
                         if item["artifactSchemaVersion"] != SUPPLEMENT and item["eventId"] in active_events]
        for item in other_engines: verify_object(item)
        discovery["artifacts"] += other_engines
        if other_engines:
            discovery["driveResearchArtifactCount"] = len(other_engines)
            if previous.get("driveResearchHandoff"):
                discovery["driveResearchHandoff"] = previous["driveResearchHandoff"]
    with temporary.open("xb") as stream:
        stream.write(canonical_json_bytes(discovery))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, pointer)
    return {"handoff": handoff, "pointerPath": str(pointer.resolve()), "forecastCount": len(published), "example": published[0] if published else None}
