"""Exact, read-only replay of one immutable V18 forecast into a local sidecar.

This script never reads outcomes, contacts a provider, writes the exchange, or
publishes a forecast.  It authenticates the retained forecast object and frozen
executables, performs counters-off and counters-on runs, and refuses any drift.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.sports_phase5 import base_out_transition as bt
from server.sports_current_statcast.mlb_v18_daily_views import _provider, _forecast_contract
from server.sports_current_statcast.mlb_v18_population_diagnostics import PopulationDiagnostics
from server.sports_current_statcast.mlb_v18_player_prop_sidecar import (
    PlayerPropCollector, build_sidecar, canonical_json_bytes, sha256_bytes, verify_sidecar,
)
from server.sports_current_statcast.mlb_v18_prospective_transform import (
    ProspectiveFrameAuthority, wrap_prospective_pipeline,
)
from server.sports_current_statcast.mlb_v18_population_geometry import reconcile_forecast
from server.sports_current_statcast.mlb_v18_whole_game_challenger import simulate_prospective_game


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_object(root: Path) -> tuple[dict, dict, dict, dict]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if root.name != manifest.get("objectSha256"):
        raise ValueError("forecast object directory differs from manifest identity")
    for member in manifest["artifacts"]:
        path = root / member["relativePath"]
        if path.stat().st_size != int(member["bytes"]) or _file_sha(path) != member["sha256"]:
            raise ValueError("forecast member checksum differs: " + member["relativePath"])
    forecast = json.loads((root / "forecast.json").read_text(encoding="utf-8"))
    execution = json.loads((root / "execution-inputs.json").read_text(encoding="utf-8"))
    evidence = json.loads((root / "pregame-evidence.json").read_text(encoding="utf-8"))
    return manifest, forecast, execution, evidence


def _population_sha(population: dict) -> str:
    cells = Counter(zip(map(int, population["awayRuns"]), map(int, population["homeRuns"])))
    rows = [{"awayScore": away, "homeScore": home, "count": count}
            for (away, home), count in sorted(cells.items())]
    return sha256_bytes(canonical_json_bytes(rows))


def _earliest_publication_receipt(forecast_root: Path, object_sha: str) -> dict[str, str]:
    pipeline_root = forecast_root.parents[2]
    matches: list[tuple[str, str, Path]] = []
    for path in (pipeline_root / "slates").glob("*/sha256/*/slate-result.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if any(row.get("objectSha256") == object_sha for row in value.get("games", [])):
            generated = str(value.get("generatedAt") or "")
            receipt_sha = str(value.get("receiptSha256") or "")
            body = {key: item for key, item in value.items() if key not in {"receiptId", "receiptSha256"}}
            if generated and len(receipt_sha) == 64 and sha256_bytes(canonical_json_bytes(body)) == receipt_sha:
                matches.append((generated, receipt_sha, path))
    if not matches:
        raise ValueError("an authenticated forecast publication receipt is unavailable")
    generated, receipt_sha, path = min(matches, key=lambda item: item[0])
    return {"forecastPublishedAt": generated, "forecastPublicationReceiptSha256": receipt_sha,
            "forecastPublicationReceiptPhysicalSha256": _file_sha(path),
            "forecastPublicationReceiptPath": str(path)}


def _lineup_binding(evidence: dict, execution: dict) -> tuple[dict, dict]:
    lineups: dict[str, list[dict]] = {}
    starters: dict[str, dict] = {}
    sides = {row["side"]: row for row in evidence["sides"]}
    inputs = execution["providerInputs"]
    for side, key, starter_key in (("AWAY", "awayBatters", "awayStarter"),
                                   ("HOME", "homeBatters", "homeStarter")):
        source = sides[side]
        if (source["lineupAuthority"].get("status") != "CONFIRMED"
                or source["lineupAuthority"].get("isComplete") is not True):
            raise ValueError(side + " lineup is not a complete confirmed authority")
        ordered = sorted(source["lineup"], key=lambda row: int(row["batting_order"]))
        templates = inputs[key]
        if len(ordered) != 9 or len(templates) != 9:
            raise ValueError(side + " lineup/template count differs")
        lineups[side] = [{
            "playerId": row["player_id"], "mlbamId": str(row["mlbam"]),
            "displayName": row["full_name"], "teamId": source["team"]["uuid"],
            "battingOrderPosition": int(row["batting_order"]),
            "modelTemplatePlayerId": str(template["batterCanonicalPlayerId"]),
        } for row, template in zip(ordered, templates, strict=True)]
        starter = source["starter"]
        template = inputs[starter_key]
        starters[side] = {
            "playerId": starter["uuid"], "mlbamId": str(starter["mlbamId"]),
            "displayName": starter["name"], "teamId": source["team"]["uuid"],
            "modelTemplatePlayerId": str(template["pitcherCanonicalPlayerId"]),
        }
    return lineups, starters


def _population_equal(left: dict, right: dict) -> dict[str, bool]:
    arrays = ("awayRuns", "homeRuns", "innings", "paCounts")
    scalars = ("simulationCount", "masterSeed", "homeWinProbability", "meanAwayRuns",
               "meanHomeRuns", "meanTotalRuns", "meanRunDifferential", "oneRunRate",
               "extraInningRate", "pitchingChangeRateAway", "pitchingChangeRateHome",
               "nonterminationCount", "illegalStateCount")
    result = {name: bool(np.array_equal(np.asarray(left[name]), np.asarray(right[name]))) for name in arrays}
    result.update({name: left[name] == right[name] for name in scalars})
    result["traces"] = left["traces"] == right["traces"]
    return result


def run(args: argparse.Namespace) -> dict:
    forecast_root = Path(args.forecast_object).resolve()
    output_root = Path(args.output_root).resolve()
    model_path = Path(args.pa_model).resolve()
    transition_path = Path(args.transition_model).resolve()
    manifest, forecast, execution, evidence = _load_object(forecast_root)
    parent = forecast["parentAuthority"]
    if _file_sha(model_path) != parent["paModelSha256"] or _file_sha(transition_path) != parent["transitionModelSha256"]:
        raise ValueError("frozen executable checksum differs from forecast binding")
    created = datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
    if created.tzinfo is None:
        raise ValueError("created-at must be timezone-aware")
    model = joblib.load(model_path)
    transition = bt.TransitionModel.from_dict(json.loads(transition_path.read_text(encoding="utf-8")))
    forecast_created = datetime.fromisoformat(forecast["forecastCreatedAt"].replace("Z", "+00:00"))
    scheduled_start = datetime.fromisoformat(forecast["scheduledStart"].replace("Z", "+00:00"))
    if forecast_created.tzinfo is None or scheduled_start.tzinfo is None or not forecast_created < scheduled_start:
        raise ValueError("retained forecast chronology is not prospective")
    authority = ProspectiveFrameAuthority(
        event_id=forecast["gameId"], game_date=str(execution["rawTemplates"][0]["game_date"])[:10],
        evidence_cutoff_utc=forecast["capturedAt"], kickoff_utc=forecast["scheduledStart"],
        snapshot_sha256=forecast["snapshotContentSha256"],
        authorized_at_utc=forecast["forecastCreatedAt"], venue_timezone=forecast["venue"]["timezone"],
    )
    real_datetime = datetime
    class ReplayClock(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return forecast_created.astimezone(tz) if tz is not None else forecast_created.replace(tzinfo=None)
    n = int(forecast["simulation"]["count"])
    common = dict(game_id=forecast["gameId"], transition_model=transition,
                  n_sims=n, master_seed=int(forecast["simulation"]["seed"]),
                  regulation=int(evidence["game"].get("scheduled_innings") or 9), trace_count=1)
    # Reconstruct the recorded pregame authorization instant without weakening
    # the live publisher guard or changing any raw/model inputs. Exact equality
    # to the immutable saved population below is the replay acceptance gate.
    with patch("server.sports_current_statcast.mlb_v18_prospective_transform.datetime", ReplayClock):
        replay_pipeline = wrap_prospective_pipeline(model, authority)
        engine = SimpleNamespace(pipeline=replay_pipeline)
        baseline_provider = _provider(engine, execution, forecast)
        collector = PlayerPropCollector(n)
        diagnostics = PopulationDiagnostics(n, regulation=common["regulation"])
        provider = diagnostics.wrap_provider(_provider(engine, execution, forecast))
    with threadpool_limits(limits=args.threads):
        baseline = simulate_prospective_game(provider=baseline_provider, **common)
        def observer(simulation, event):
            diagnostics(simulation, event)
            collector(simulation, event)
        instrumented = simulate_prospective_game(provider=provider, event_observer=observer, **common)
    off_on = _population_equal(baseline, instrumented)
    saved = _population_equal(baseline, execution["population"])
    forecast_reconciliation = reconcile_forecast(baseline, _forecast_contract(forecast))
    if not all(off_on.values()) or not all(saved.values()) or not forecast_reconciliation["allMetricsMatch"]:
        raise ValueError("instrumentation or exact forecast replay changed the numerical population")
    diagnostic_arrays, diagnostic_meta = diagnostics.finalize(instrumented)
    accounting = collector.finalize(instrumented, diagnostic_arrays=diagnostic_arrays)
    lineups, starters = _lineup_binding(evidence, execution)
    population_sha = _population_sha(baseline)
    publication = _earliest_publication_receipt(forecast_root, manifest["objectSha256"])
    binding = {
        "gameId": forecast["gameId"], "sourceGameId": str(forecast["sourceGameId"]),
        "forecastId": manifest["objectId"], "forecastObjectSha256": manifest["objectSha256"],
        "populationSha256": population_sha, "modelId": "MLB_V18_HGB_PA",
        "modelArtifactSha256": parent["paModelSha256"],
        "transitionArtifactSha256": parent["transitionModelSha256"],
        "parentBundleSha256": parent["bundleSha256"], "sourceCutoff": forecast["sourceCutoff"],
        "forecastCreatedAt": forecast["forecastCreatedAt"], "forecastCapturedAt": forecast["capturedAt"],
        **publication,
        "scheduledStart": forecast["scheduledStart"], "simulationCount": n,
        "masterSeed": int(forecast["simulation"]["seed"]),
        "lineupAuthorities": forecast["lineupAuthorities"], "starters": forecast["starters"],
    }
    payload, sidecar_sha = build_sidecar(collector=collector, accounting=accounting,
        binding=binding, lineups=lineups, starters=starters, created_at=created.isoformat())
    verify_sidecar(payload, sidecar_sha)
    target = output_root / "objects" / "sha256" / sidecar_sha
    staging = output_root / ".staging" / str(uuid.uuid4())
    staging.mkdir(parents=True, exist_ok=False)
    (staging / "sidecar.json").write_bytes(payload)
    receipt = {
        "schemaVersion": "MLB_V18_PLAYER_PROP_SIDECAR_REPLAY_RECEIPT_V1",
        "sidecarSha256": sidecar_sha, "sidecarBytes": len(payload),
        "forecastObjectSha256": manifest["objectSha256"], "forecastObjectPath": str(forecast_root),
        "originalPopulationSha256": population_sha,
        "invariance": {"countersOffEqualsCountersOn": off_on, "replayEqualsSavedPopulation": saved,
                       "forecastSummaryReconciles": forecast_reconciliation},
        "accounting": accounting,
        "diagnosticAccounting": diagnostic_meta["accounting"],
        "operations": {"modelFits": 0, "providerCalls": 0, "providerBytes": 0, "providerCostUsd": 0,
                       "outcomeReads": 0, "sealedReads": 0, "aispWrites": 0, "exchangeWrites": 0,
                       "forecastPublications": 0},
    }
    receipt_bytes = canonical_json_bytes(receipt)
    (staging / "replay-receipt.json").write_bytes(receipt_bytes)
    package_manifest = {
        "schemaVersion": "MLB_V18_PLAYER_PROP_SIDECAR_MANIFEST_V1",
        "sidecarSha256": sidecar_sha,
        "members": [
            {"relativePath": "sidecar.json", "bytes": len(payload), "sha256": sidecar_sha},
            {"relativePath": "replay-receipt.json", "bytes": len(receipt_bytes), "sha256": sha256_bytes(receipt_bytes)},
        ],
        "publication": "LOCAL_RESEARCH_ARTIFACT_ONLY_NOT_EXCHANGE",
    }
    manifest_bytes = canonical_json_bytes(package_manifest)
    (staging / "manifest.json").write_bytes(manifest_bytes)
    if target.exists():
        for source in staging.iterdir():
            existing = target / source.name
            if not existing.is_file() or existing.read_bytes() != source.read_bytes():
                raise ValueError("existing sidecar object differs from deterministic replay")
        shutil.rmtree(staging)
        disposition = "REUSED_BYTE_IDENTICAL"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)
        disposition = "CREATED"
    result = {"sidecarSha256": sidecar_sha, "sidecarBytes": len(payload),
              "manifestSha256": sha256_bytes(manifest_bytes), "receiptSha256": sha256_bytes(receipt_bytes),
              "populationSha256": population_sha, "objectPath": str(target), "disposition": disposition,
              "invarianceAllPassed": all(off_on.values()) and all(saved.values()),
              "accountingAllPassed": accounting["allPassed"]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--forecast-object", required=True)
    value.add_argument("--pa-model", required=True)
    value.add_argument("--transition-model", required=True)
    value.add_argument("--output-root", required=True)
    value.add_argument("--created-at", required=True)
    value.add_argument("--threads", type=int, default=4)
    return value


if __name__ == "__main__":
    run(parser().parse_args())
