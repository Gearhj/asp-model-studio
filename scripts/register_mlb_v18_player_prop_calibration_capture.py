"""Register or dry-run one outcome-free V18 player-prop calibration capture.

This inactive adapter reads only an immutable forecast package and an optional
local player-prop sidecar.  It never reads results or publishes to the exchange.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.sports_current_statcast.mlb_v18_player_prop_calibration import build_capture_record


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _forecast(root: Path) -> tuple[dict, dict, dict]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if root.name != manifest.get("objectSha256"):
        raise ValueError("forecast directory differs from manifest object identity")
    for member in manifest.get("artifacts", []):
        path = root / member["relativePath"]
        if path.stat().st_size != int(member["bytes"]) or _sha(path) != member["sha256"]:
            raise ValueError("forecast package member differs: " + member["relativePath"])
    return (
        manifest,
        json.loads((root / "forecast.json").read_text(encoding="utf-8")),
        json.loads((root / "pregame-evidence.json").read_text(encoding="utf-8")),
    )


def _sidecar(root: Path | None) -> tuple[bytes | None, str | None]:
    if root is None:
        return None, None
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for member in manifest.get("members", []):
        path = root / member["relativePath"]
        if path.stat().st_size != int(member["bytes"]) or _sha(path) != member["sha256"]:
            raise ValueError("sidecar package member differs: " + member["relativePath"])
    payload = (root / "sidecar.json").read_bytes()
    return payload, manifest["sidecarSha256"]


def run(args: argparse.Namespace) -> dict:
    manifest, forecast, evidence = _forecast(Path(args.forecast_object).resolve())
    sidecar_payload, sidecar_sha = _sidecar(
        Path(args.sidecar_object).resolve() if args.sidecar_object else None
    )
    payload, digest = build_capture_record(
        forecast_manifest=manifest,
        forecast=forecast,
        pregame_evidence=evidence,
        sidecar_payload=sidecar_payload,
        sidecar_sha256=sidecar_sha,
        model_training_end=date.fromisoformat(args.model_training_end),
        recorded_at=args.recorded_at,
        historical_feature_chronology=args.historical_feature_chronology,
    )
    document = json.loads(payload)
    result = {
        "captureSha256": digest,
        "captureBytes": len(payload),
        "disposition": document["disposition"],
        "assessmentEligible": document["assessmentEligible"],
        "gameId": document["game"]["gameId"],
        "forecastObjectSha256": document["forecast"]["objectSha256"],
        "writeDisposition": "DRY_RUN_NO_WRITE",
    }
    if args.output_root:
        target = Path(args.output_root).resolve() / "objects" / "sha256" / digest
        staging = target.parent.parent.parent / ".staging" / uuid.uuid4().hex
        staging.mkdir(parents=True, exist_ok=False)
        (staging / "capture.json").write_bytes(payload)
        if target.exists():
            existing = target / "capture.json"
            if not existing.is_file() or existing.read_bytes() != payload:
                raise ValueError("existing capture address contains different bytes")
            shutil.rmtree(staging)
            result["writeDisposition"] = "REUSED_BYTE_IDENTICAL"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
            result["writeDisposition"] = "CREATED_LOCAL_RESEARCH_OBJECT"
        result["objectPath"] = str(target)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--forecast-object", required=True)
    value.add_argument("--sidecar-object")
    value.add_argument("--model-training-end", required=True)
    value.add_argument("--recorded-at", required=True)
    value.add_argument(
        "--historical-feature-chronology",
        choices=("CERTIFIED", "UNCERTIFIED_HISTORICAL_FEATURE_CHRONOLOGY"),
        required=True,
    )
    value.add_argument("--output-root")
    return value


if __name__ == "__main__":
    run(parser().parse_args())
