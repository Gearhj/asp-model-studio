"""Outcome-free prospective player-prop capture for the natural V18 owner.

The module finalizes the passive observer attached to the owner's one original
5,000-draw population.  It writes only private, content-addressed research
objects below ``outputs``.  It never reads results, calls a provider, writes the
exchange, or changes forecast/model authority.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Mapping
import uuid
from zoneinfo import ZoneInfo

import numpy as np

from . import mlb_v18_daily_slate as daily
from .mlb_v18_player_prop_calibration import build_capture_record
from .mlb_v18_player_prop_sidecar import (
    PlayerPropCollector,
    build_sidecar,
    canonical_json_bytes,
    sha256_bytes,
    verify_sidecar,
)


SCHEMA_VERSION = "MLB_V18_PROSPECTIVE_PLAYER_PROP_CAPTURE_PACKAGE_V1"
FAILURE_SCHEMA_VERSION = "MLB_V18_PROSPECTIVE_PLAYER_PROP_CAPTURE_FAILURE_V1"
DISCOVERY_SCHEMA_VERSION = "MLB_V18_PROSPECTIVE_PLAYER_PROP_CAPTURE_DISCOVERY_V1"
OUTPUT_NAME = "mlb-v18-player-prop-prospective-v1"
MODEL_TRAINING_END = date(2026, 5, 1)
HISTORICAL_FEATURE_CHRONOLOGY = "UNCERTIFIED_HISTORICAL_FEATURE_CHRONOLOGY"
PROSPECTIVE_PLAN = {
    "schemaVersion": "MLB_V18_PLAYER_PROP_PROSPECTIVE_CALIBRATION_PLAN_V1",
    "physicalSha256": "3aa6219a3b8315b111d87a56b3e9353572ce8d35dec6fe5bc384a96b1a6afa4a",
    "relativePath": "docs/mlb-player-prop-calibration-v1/PROSPECTIVE_CAPTURE_PLAN.json",
    "roleRule": (
        "DEVELOPMENT_ONLY_UNTIL_A_SEPARATE_AUTHORIZED_DATE_ATOMIC_CLOSURE_RECEIPT_"
        "FREEZES_THE_METHOD_BEFORE_ANY_VALIDATION_RESULT_ACCESS"
    ),
}
AUTHORITY = {
    "researchOnly": True,
    "outcomeAccess": False,
    "exchangePublication": False,
    "aispWrite": False,
    "aispDisplay": False,
    "calibrationFit": False,
    "modelPromotion": False,
    "wagering": False,
}


class FailOpenPlayerPropObserver:
    """Disable only the research observer after its first internal failure."""

    def __init__(self, collector: PlayerPropCollector) -> None:
        self.collector = collector
        self.failure_category: str | None = None

    def __call__(self, simulation: int, event: Mapping[str, Any]) -> None:
        if self.failure_category is not None:
            return
        try:
            self.collector(simulation, event)
        except Exception as exc:
            self.failure_category = getattr(exc, "code", type(exc).__name__)


def _reference(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(payload), "sha256": sha256_bytes(payload)}


def _contained(path: Path, root: Path) -> Path:
    resolved, boundary = path.resolve(strict=True), root.resolve(strict=True)
    if not resolved.is_relative_to(boundary):
        raise ValueError("CAPTURE_REFERENCE_OUTSIDE_PRIVATE_ROOT")
    return resolved


def _write_once(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
        return "CREATED"
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ValueError("IMMUTABLE_CAPTURE_INDEX_CONFLICT") from None
        return "REUSED_BYTE_IDENTICAL"


def _atomic_object(root: Path, digest: str, members: Mapping[str, bytes]) -> tuple[Path, str]:
    target = root / "objects" / "sha256" / digest
    staging = root / ".staging" / uuid.uuid4().hex
    staging.mkdir(parents=True, exist_ok=False)
    try:
        for name, payload in members.items():
            (staging / name).write_bytes(payload)
        if target.exists():
            for name, payload in members.items():
                path = target / name
                if not path.is_file() or path.read_bytes() != payload:
                    raise ValueError("IMMUTABLE_CAPTURE_OBJECT_CONFLICT")
            shutil.rmtree(staging)
            return target, "REUSED_BYTE_IDENTICAL"
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)
        return target, "CREATED"
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def planned_forecast_manifest(snapshot: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """Compute the exact immutable object identity without writing forecast bytes."""
    mapping = {
        "forecast.json": payload["forecast"],
        "pregame-evidence.json": payload["evidence"],
        "execution-inputs.json": payload["executionInputs"],
        "representative-path.json": payload["representativePath"],
    }
    artifacts = []
    for name in sorted(mapping):
        raw = daily.canonical_json_bytes(daily.json_safe(mapping[name]))
        artifacts.append({"relativePath": name, "bytes": len(raw), "sha256": daily.sha_bytes(raw)})
    body = {
        "schemaVersion": "MLB_V18_DAILY_GAME_OBJECT_MANIFEST_V1",
        "publicationKey": daily.publication_key(snapshot),
        "gameId": snapshot["game"]["game_id"],
        "parentBundleSha256": daily.PARENT_BUNDLE_SHA256,
        "artifacts": artifacts,
        **daily.RESEARCH_FLAGS,
    }
    object_sha = daily.sha_json(body)
    return {**body, "objectId": f"mlb-v18-daily-game-{object_sha[:24]}", "objectSha256": object_sha}


def _population_sha(population: Mapping[str, Any]) -> str:
    away = np.asarray(population["awayRuns"], dtype=np.int64)
    home = np.asarray(population["homeRuns"], dtype=np.int64)
    cells: dict[tuple[int, int], int] = {}
    for pair in zip(away.tolist(), home.tolist(), strict=True):
        cells[pair] = cells.get(pair, 0) + 1
    rows = [
        {"awayScore": away_score, "homeScore": home_score, "count": count}
        for (away_score, home_score), count in sorted(cells.items())
    ]
    return sha256_bytes(canonical_json_bytes(rows))


def _participant_bindings(evidence: Mapping[str, Any], execution: Mapping[str, Any]):
    lineups: dict[str, list[dict[str, Any]]] = {}
    starters: dict[str, dict[str, Any]] = {}
    sides = {str(row["side"]).upper(): row for row in evidence["sides"]}
    inputs = execution["providerInputs"]
    for side, batter_key, starter_key in (
        ("AWAY", "awayBatters", "awayStarter"),
        ("HOME", "homeBatters", "homeStarter"),
    ):
        source = sides[side]
        authority = source.get("lineupAuthority") or {}
        if authority.get("status") != "CONFIRMED" or authority.get("isComplete") is not True:
            raise ValueError(f"{side}_LINEUP_NOT_COMPLETE_CONFIRMED")
        ordered = sorted(source["lineup"], key=lambda row: int(row["batting_order"]))
        templates = list(inputs[batter_key])
        if len(ordered) != 9 or len(templates) != 9:
            raise ValueError(f"{side}_LINEUP_TEMPLATE_COUNT_MISMATCH")
        lineups[side] = [{
            "playerId": str(row["player_id"]),
            "mlbamId": str(row["mlbam"]),
            "displayName": str(row.get("full_name") or ""),
            "teamId": str(source["team"]["uuid"]),
            "battingOrderPosition": int(row["batting_order"]),
            "modelTemplatePlayerId": str(template["batterCanonicalPlayerId"]),
        } for row, template in zip(ordered, templates, strict=True)]
        starter, template = source["starter"], inputs[starter_key]
        starters[side] = {
            "playerId": str(starter["uuid"]),
            "mlbamId": str(starter["mlbamId"]),
            "displayName": str(starter.get("name") or ""),
            "teamId": str(source["team"]["uuid"]),
            "modelTemplatePlayerId": str(template["pitcherCanonicalPlayerId"]),
        }
    return lineups, starters


def collector_memory_bytes(collector: PlayerPropCollector) -> int:
    return collector.allocated_bytes()


def finalize_and_register(
    *,
    collector: PlayerPropCollector,
    forecast_manifest: Mapping[str, Any],
    payload: Mapping[str, Any],
    output_root: Path,
    created_at: datetime | None = None,
    observer_seconds: float | None = None,
) -> dict[str, Any]:
    """Finalize, authenticate and atomically register one pregame capture."""
    started = time.perf_counter()
    created = created_at or datetime.now(timezone.utc)
    if created.tzinfo is None:
        raise ValueError("CAPTURE_CREATION_TIME_MUST_BE_AWARE")
    forecast = payload["forecast"]
    scheduled = datetime.fromisoformat(str(forecast["scheduledStart"]).replace("Z", "+00:00"))
    if created >= scheduled:
        raise ValueError("PROSPECTIVE_CAPTURE_AFTER_SCHEDULED_START")
    population = payload["executionInputs"]["population"]
    accounting = collector.finalize(population)
    lineups, starters = _participant_bindings(payload["evidence"], payload["executionInputs"])
    parent = forecast["parentAuthority"]
    binding = {
        "gameId": forecast["gameId"],
        "sourceGameId": str(forecast["sourceGameId"]),
        "forecastId": forecast_manifest["objectId"],
        "forecastObjectSha256": forecast_manifest["objectSha256"],
        "populationSha256": _population_sha(population),
        "modelId": "MLB_V18_HGB_PA",
        "modelArtifactSha256": parent["paModelSha256"],
        "transitionArtifactSha256": parent["transitionModelSha256"],
        "parentBundleSha256": parent["bundleSha256"],
        "sourceCutoff": forecast["sourceCutoff"],
        "forecastCreatedAt": forecast["forecastCreatedAt"],
        "forecastCapturedAt": forecast["capturedAt"],
        "scheduledStart": forecast["scheduledStart"],
        "simulationCount": int(forecast["simulation"]["count"]),
        "masterSeed": int(forecast["simulation"]["seed"]),
        "lineupAuthorities": forecast["lineupAuthorities"],
        "starters": forecast["starters"],
    }
    sidecar_payload, sidecar_sha = build_sidecar(
        collector=collector,
        accounting=accounting,
        binding=binding,
        lineups=lineups,
        starters=starters,
        created_at=created.isoformat(),
    )
    verify_sidecar(sidecar_payload, sidecar_sha)
    capture_payload, capture_sha = build_capture_record(
        forecast_manifest=forecast_manifest,
        forecast=forecast,
        pregame_evidence=payload["evidence"],
        sidecar_payload=sidecar_payload,
        sidecar_sha256=sidecar_sha,
        model_training_end=MODEL_TRAINING_END,
        recorded_at=created.isoformat(),
        historical_feature_chronology=HISTORICAL_FEATURE_CHRONOLOGY,
    )
    role_date = scheduled.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    lead_seconds = (scheduled - created).total_seconds()
    registration = {
        "schemaVersion": "MLB_V18_PLAYER_PROP_PROSPECTIVE_REGISTRATION_V1",
        "registeredAt": created.isoformat(),
        "gameId": forecast["gameId"],
        "sourceGameId": str(forecast["sourceGameId"]),
        "forecastObjectSha256": forecast_manifest["objectSha256"],
        "sidecarSha256": sidecar_sha,
        "captureSha256": capture_sha,
        "role": "DEVELOPMENT",
        "roleDateAmericaNewYork": role_date,
        "roleDateAtomic": True,
        "developmentClosureReceipt": None,
        "validationResultAccessAuthorized": False,
        "prospectivePlan": PROSPECTIVE_PLAN,
        "timing": {
            "scheduledStart": scheduled.isoformat(),
            "leadSecondsAtRegistration": lead_seconds,
            "registeredBeforeStart": True,
            "registeredAtOrBeforeT45": lead_seconds >= 45 * 60,
            "observerSeconds": observer_seconds,
        },
        "resourceAccounting": {
            "collectorArrayBytes": collector_memory_bytes(collector),
            "sidecarBytes": len(sidecar_payload),
            "providerCalls": 0,
            "providerBytes": 0,
            "providerCostUsd": 0,
            "outcomeReads": 0,
            "sealedReads": 0,
            "aispWrites": 0,
            "exchangeWrites": 0,
            "additionalSimulationDraws": 0,
        },
        "authority": AUTHORITY,
    }
    # The measured duration is intentionally excluded from the content identity:
    # package replay is byte-stable for the same captured evidence and clock.
    registration_payload = canonical_json_bytes(registration)
    member_records = [
        {"relativePath": "capture.json", "bytes": len(capture_payload), "sha256": capture_sha},
        {"relativePath": "registration.json", "bytes": len(registration_payload), "sha256": sha256_bytes(registration_payload)},
        {"relativePath": "sidecar.json", "bytes": len(sidecar_payload), "sha256": sidecar_sha},
    ]
    manifest_body = {
        "schemaVersion": SCHEMA_VERSION,
        "forecastObjectSha256": forecast_manifest["objectSha256"],
        "gameId": forecast["gameId"],
        "members": member_records,
        "publication": "PRIVATE_LOCAL_RESEARCH_CAPTURE_NOT_EXCHANGE",
        "prospectivePlanSha256": PROSPECTIVE_PLAN["physicalSha256"],
        "role": "DEVELOPMENT",
        "authority": AUTHORITY,
    }
    package_sha = sha256_bytes(canonical_json_bytes(manifest_body))
    manifest = {**manifest_body, "packageId": f"mlb-v18-prop-capture-{package_sha[:24]}",
                "packageSha256": package_sha}
    manifest_payload = canonical_json_bytes(manifest)
    root = Path(output_root).resolve()
    target, object_disposition = _atomic_object(root, package_sha, {
        "capture.json": capture_payload,
        "registration.json": registration_payload,
        "sidecar.json": sidecar_payload,
        "manifest.json": manifest_payload,
    })
    package_ref = {"path": str(target), "sha256": package_sha,
                   "manifestPhysicalSha256": sha256_bytes(manifest_payload)}
    discovery = {
        "schemaVersion": DISCOVERY_SCHEMA_VERSION,
        "gameId": forecast["gameId"],
        "sourceGameId": str(forecast["sourceGameId"]),
        "forecastObjectSha256": forecast_manifest["objectSha256"],
        "package": package_ref,
        "role": "DEVELOPMENT",
        "roleDateAmericaNewYork": role_date,
        "createdAt": created.isoformat(),
        "assessmentEligible": True,
        "authority": AUTHORITY,
    }
    discovery_payload = canonical_json_bytes(discovery)
    discovery_path = root / "discovery" / "sha256" / f"{package_sha}.json"
    discovery_disposition = _write_once(discovery_path, discovery_payload)
    key_payload = canonical_json_bytes({
        "schemaVersion": "MLB_V18_PLAYER_PROP_CAPTURE_FORECAST_KEY_V1",
        "forecastObjectSha256": forecast_manifest["objectSha256"],
        "packageSha256": package_sha,
        "discovery": _reference(discovery_path),
    })
    key_disposition = _write_once(
        root / "forecast-keys" / f"{forecast_manifest['objectSha256']}.json", key_payload
    )
    elapsed = time.perf_counter() - started
    operation = {
        "schemaVersion": "MLB_V18_PLAYER_PROP_CAPTURE_OPERATION_RECEIPT_V1",
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "gameId": forecast["gameId"],
        "forecastObjectSha256": forecast_manifest["objectSha256"],
        "packageSha256": package_sha,
        "observerSeconds": observer_seconds,
        "finalizeAndWriteSeconds": elapsed,
        "collectorArrayBytes": collector_memory_bytes(collector),
        "sidecarBytes": len(sidecar_payload),
        "packageMemberBytes": sum(len(value) for value in (
            capture_payload, registration_payload, sidecar_payload, manifest_payload,
        )),
        "leadSecondsAtRegistration": lead_seconds,
        "providerCalls": 0,
        "outcomeReads": 0,
        "aispWrites": 0,
        "additionalSimulationDraws": 0,
        "authority": AUTHORITY,
    }
    operation_payload = canonical_json_bytes(operation)
    operation_sha = sha256_bytes(operation_payload)
    operation_path = root / "operations" / "sha256" / operation_sha / "operation.json"
    _write_once(operation_path, operation_payload)
    return {
        "status": "PROSPECTIVE_CAPTURE_REGISTERED",
        "packageSha256": package_sha,
        "packagePath": str(target),
        "manifestPhysicalSha256": sha256_bytes(manifest_payload),
        "sidecarSha256": sidecar_sha,
        "sidecarBytes": len(sidecar_payload),
        "captureSha256": capture_sha,
        "captureBytes": len(capture_payload),
        "registrationSha256": sha256_bytes(registration_payload),
        "registrationBytes": len(registration_payload),
        "discovery": _reference(discovery_path),
        "objectDisposition": object_disposition,
        "discoveryDisposition": discovery_disposition,
        "forecastKeyDisposition": key_disposition,
        "role": "DEVELOPMENT",
        "roleDateAmericaNewYork": role_date,
        "leadSecondsAtRegistration": lead_seconds,
        "collectorArrayBytes": collector_memory_bytes(collector),
        "finalizeAndWriteSeconds": elapsed,
        "operationReceipt": _reference(operation_path),
        "providerCalls": 0,
        "outcomeReads": 0,
        "additionalSimulationDraws": 0,
    }


def existing_capture(output_root: Path, forecast_object_sha256: str) -> dict[str, Any] | None:
    root = Path(output_root).resolve()
    path = root / "forecast-keys" / f"{forecast_object_sha256}.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_bytes())
    discovery = value.get("discovery") or {}
    discovery_path = _contained(Path(str(discovery.get("path") or "")), root)
    if not discovery_path.is_file() or _reference(discovery_path) != discovery:
        raise ValueError("CAPTURE_DISCOVERY_REFERENCE_INVALID")
    return json.loads(discovery_path.read_bytes())


def write_failure_receipt(
    *, output_root: Path, game_id: str, forecast_object_sha256: str,
    category: str, recorded_at: datetime | None = None,
) -> dict[str, Any]:
    now = recorded_at or datetime.now(timezone.utc)
    body = {
        "schemaVersion": FAILURE_SCHEMA_VERSION,
        "recordedAt": now.isoformat(),
        "gameId": str(game_id),
        "forecastObjectSha256": str(forecast_object_sha256),
        "category": str(category),
        "forecastPublicationContinues": True,
        "outcomeAccess": False,
        "providerCalls": 0,
        "aispWrites": 0,
        "authority": AUTHORITY,
    }
    payload = canonical_json_bytes(body)
    digest = sha256_bytes(payload)
    root = Path(output_root).resolve()
    path = root / "failures" / "sha256" / digest / "failure.json"
    disposition = _write_once(path, payload)
    return {"status": "PLAYER_PROP_CAPTURE_FAILED_FORECAST_CONTINUES",
            "failureSha256": digest, "failure": _reference(path), "disposition": disposition}


__all__ = [
    "AUTHORITY", "FailOpenPlayerPropObserver", "OUTPUT_NAME", "PROSPECTIVE_PLAN", "collector_memory_bytes",
    "existing_capture", "finalize_and_register", "planned_forecast_manifest",
    "write_failure_receipt",
]
