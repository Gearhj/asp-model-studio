from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/cfb-gen1-current-v1"
DEFAULT_EXCHANGE = ROOT.parent / "asp-model-exchange/cfb-gen1-research-v1/current-v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "physicalSha256": sha(path)}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode("utf-8")
    path.write_bytes(raw)
    if path.read_bytes() != raw:
        raise RuntimeError("publication byte replay failed")


def verify_package(package: Path) -> dict[str, Any]:
    index_path = package / "index.json"
    digest = sha(index_path)
    if package.name != digest:
        raise RuntimeError("package directory is not the physical index digest")
    index = json.loads(index_path.read_bytes())
    if index.get("rawProviderResponsesIncluded") is not False:
        raise RuntimeError("provider raw responses must not enter the exchange")
    for item in index["files"]:
        path = package / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha(path) != item["physicalSha256"]:
            raise RuntimeError(f"package artifact mismatch: {item['path']}")
    forecast = json.loads((package / "forecast.json").read_bytes())
    if forecast["forecastId"] != index["forecastId"] or forecast["game"]["game_id"] != index["gameId"]:
        raise RuntimeError("forecast/index identity mismatch")
    if not forecast["researchOnly"] or forecast["aispAuthority"] or forecast["wageringAuthority"]:
        raise RuntimeError("research authority flags changed")
    return index


def publish(exchange: Path) -> dict[str, Any]:
    artifact_index = json.loads((OUTPUT / "artifact-index.json").read_bytes())
    digest = artifact_index["packageDigest"]
    source = OUTPUT / "packages/sha256" / digest
    index = verify_package(source)
    expected = (ROOT.parent / "asp-model-exchange/cfb-gen1-research-v1/current-v1").resolve()
    if exchange.resolve() != expected:
        raise RuntimeError("unexpected College Football exchange namespace")
    destination = exchange / "packages/sha256" / digest
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        target = destination / path.name
        if target.exists():
            if target.stat().st_size != path.stat().st_size or sha(target) != sha(path):
                raise RuntimeError(f"immutable exchange collision: {target}")
        else:
            shutil.copy2(path, target)
    verify_package(destination)
    receipt_path = destination / "publication-receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_bytes())
    else:
        receipt = {
            "schemaVersion": "CFB_GEN1_RESEARCH_EXCHANGE_PUBLICATION_RECEIPT_V1",
            "publishedAtUtc": datetime.now(timezone.utc).isoformat(),
            "packageDigest": digest, "forecastId": index["forecastId"], "gameId": index["gameId"],
            "sourcePackage": ref(source / "index.json"),
            "deliveredFiles": [ref(destination / path.name) for path in sorted(source.iterdir())],
            "rawProviderResponsesDelivered": False, "researchOnly": True,
            "aispAuthority": False, "wageringAuthority": False, "schedulerAuthority": False,
            "consumerAcknowledgement": None,
        }
        write_json(receipt_path, receipt)
    handoff_path = destination / "CLAUDE_HANDOFF.md"
    if not handoff_path.exists():
        forecast = json.loads((destination / "forecast.json").read_bytes())
        handoff = f"""# Future Claude handoff — College Football Gen 1 current research

This package is retained for later review; no immediate import is requested during the MLB/NFL closeout.

- Package: `{destination}`
- Index SHA-256: `{digest}`
- Forecast: `{index['forecastId']}`
- Game: Syracuse at Pittsburgh, CFBD `{index['gameId']}`, kickoff `{forecast['game']['scheduled_at']}`
- Baseline: `{forecast['baseline']['configuration']}`, {forecast['baseline']['drawCount']:,} paired score draws, zero tie probability.
- Ridge point/winner probabilities, Elo winner probabilities, and joint-residual winner probabilities are separate fields.
- Provider raw responses are excluded. Research only; no AISP, wagering, odds, scheduler, or promotion authority.
"""
        handoff_path.write_text(handoff, encoding="utf-8")
    pointer = {
        "schemaVersion": "CFB_GEN1_RESEARCH_EXCHANGE_POINTER_V1",
        "packageDigest": digest, "forecastId": index["forecastId"], "gameId": index["gameId"],
        "package": str(destination.resolve()), "index": ref(destination / "index.json"),
        "publicationReceipt": ref(receipt_path), "handoff": ref(handoff_path),
        "consumerAcknowledgement": None,
    }
    write_json(exchange / "current.json", pointer)
    local_receipt = OUTPUT / "exchange-publication-receipt.json"
    write_json(local_receipt, {**receipt, "exchangePackage": str(destination.resolve()), "exchangePointer": ref(exchange / "current.json"), "exchangeHandoff": ref(handoff_path)})
    delivery_index = OUTPUT / "delivery-index.json"
    write_json(delivery_index, {
        "schemaVersion": "CFB_GEN1_CURRENT_DELIVERY_INDEX_V1",
        "artifactIndex": ref(OUTPUT / "artifact-index.json"),
        "packageDigest": digest, "forecastId": index["forecastId"], "gameId": index["gameId"],
        "exchangePackage": str(destination.resolve()), "exchangeIndex": ref(destination / "index.json"),
        "publicationReceipt": ref(receipt_path), "handoff": ref(handoff_path), "currentPointer": ref(exchange / "current.json"),
        "producedForecasts": 1, "publishedForecasts": 1,
        "importConfirmedForecasts": 0, "displayConfirmedForecasts": 0,
        "consumerAcknowledgement": receipt["consumerAcknowledgement"],
        "independentVerification": ref(OUTPUT / "independent-verification.json") if (OUTPUT / "independent-verification.json").is_file() else None,
    })
    return {
        "status": "PUBLISHED" if receipt["consumerAcknowledgement"] is None else "PUBLISHED_AND_ACKNOWLEDGED",
        "package": str(destination.resolve()), "packageDigest": digest,
        "forecastId": index["forecastId"], "publicationReceipt": ref(receipt_path),
        "handoff": ref(handoff_path), "current": ref(exchange / "current.json"),
        "deliveryIndex": ref(delivery_index),
        "consumerAcknowledgement": receipt["consumerAcknowledgement"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange-root", type=Path, default=DEFAULT_EXCHANGE)
    args = parser.parse_args()
    print(json.dumps(publish(args.exchange_root), indent=2, sort_keys=True))
