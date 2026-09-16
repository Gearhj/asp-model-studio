"""Immutable eligibility evidence for separately authorized paper research.

This module binds an existing forecast and its retained population.  It does
not execute a model, obtain a quote, create an account, or grant real-money
authority.  The wire encoding intentionally matches AISP's canonical UTF-8
research-supplement contract.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


KIND = "PAPER_RESEARCH_ELIGIBILITY"
SCHEMA = "AISP_RESEARCH_SUPPLEMENT_V1"
MANIFEST_SCHEMA = "AISP_RESEARCH_SUPPLEMENT_MANIFEST_V1"
GOVERNANCE = {
    "status": "RESEARCH_SHADOW",
    "researchShadowOnly": True,
    "executionAllowedInAisp": False,
    "modelPromotionAllowed": False,
    "wageringAuthority": False,
}


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def physical(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def require_physical(reference: dict[str, Any]) -> None:
    actual = physical(Path(reference["path"]))
    expected = {key: reference[key] for key in ("path", "sha256", "bytes")}
    if actual != expected:
        raise ValueError(f"Evidence bytes differ: {reference['path']}")


def immutable_bytes(path: Path, raw: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"Immutable object already differs: {path}")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    if path.read_bytes() != raw:
        raise ValueError(f"Written bytes differ: {path}")
    return physical(path)


def immutable_json(path: Path, value: object) -> dict[str, Any]:
    return immutable_bytes(path, canonical_json_bytes(value))


def package_address(manifest_without_address: dict[str, Any]) -> str:
    """Logical package identity; distinct from the manifest's physical hash."""
    return hashlib.sha256(canonical_json_bytes(manifest_without_address)).hexdigest()


def validate_policy(policy: dict[str, Any]) -> None:
    required = {
        "mode": "VIRTUAL_RESEARCH_ONLY",
        "virtualInitialBankrollUsd": 1000,
        "marketScope": ["MONEYLINE"],
        "kellyFraction": 0.25,
        "positionCapFraction": 0.005,
        "initialPositionCapUsd": 5,
        "sameGameCapFraction": 0.01,
        "dailyCapFraction": 0.02,
        "minimumAdjustedEdgeFraction": 0.02,
        "realMoneyExecutionAllowed": False,
        "wageringOutsideAispAllowed": False,
        "modelPromotionClaim": False,
    }
    for key, expected in required.items():
        if policy.get(key) != expected:
            raise ValueError(f"Policy differs at {key}")
    if not policy.get("experimentId"):
        raise ValueError("Missing experiment identity")


def validate_document(document: dict[str, Any]) -> None:
    if document.get("schemaVersion") != SCHEMA or document.get("kind") != KIND:
        raise ValueError("Unsupported supplement contract")
    if document.get("governance") != GOVERNANCE:
        raise ValueError("Producer authority changed")
    if document.get("sport") not in {"NBA", "CFB"}:
        raise ValueError("Unsupported sport")
    validate_policy(document["summaries"]["authorization"])
    binding = document["binding"]
    population = document["summaries"]["frozenForecast"]["population"]
    if binding["forecastId"] != population["forecastId"]:
        raise ValueError("Forecast/population binding differs")
    if population["drawCount"] != 10_000:
        raise ValueError("Original joint population was not preserved")
    if document["simulation"] != {"kind": "NONE", "count": 0}:
        raise ValueError("Eligibility may not claim a new simulation")
    frozen = document["summaries"]["frozenConfiguration"]
    controlling = {
        "awayWin": frozen["awayWinProbability"],
        "homeWin": frozen["homeWinProbability"],
        "tie": frozen["tieProbability"],
    }
    declared = document["summaries"]["probabilityChannels"]["controllingJoint"]
    if declared != controlling:
        raise ValueError("Controlling probability mass differs from frozen configuration")
    if abs(sum(controlling.values()) - 1.0) > 1e-12:
        raise ValueError("Controlling probability mass differs")
    if controlling.get("tie") != 0:
        raise ValueError("NBA/CFB moneyline binding must have zero final tie mass")
    authorization = document["summaries"]["authorization"]
    for key in ("policyVersion", "consumerVirtualExperimentAuthorized", "realMoneyAuthorized"):
        if key not in authorization:
            raise ValueError(f"Missing consumer eligibility field {key}")
    if authorization["consumerVirtualExperimentAuthorized"] is not True or authorization["realMoneyAuthorized"] is not False:
        raise ValueError("Consumer/real-money authority differs")
    if document["summaries"]["probabilitySemantics"].get("settlementMustBeExplicit") is not True:
        raise ValueError("Settlement semantics differ")
    if frozen.get("executionAllowed") is not False or frozen.get("modelPromotionAllowed") is not False:
        raise ValueError("Frozen configuration authority differs")
    for reference in document["producer"]["physicalReferences"]:
        require_physical(reference)
    if document["summaries"]["authorization"]["quoteAuthority"] != (
        "SPORTSGAMEODDS_RESEARCH_QUOTES_ONLY_UNDER_SEPARATE_CONSUMER_POLICY"
    ):
        raise ValueError("Quote authority differs")


def verify_package(directory: Path) -> dict[str, Any]:
    if {path.name for path in directory.iterdir()} != {"manifest.json", "supplement.json"}:
        raise ValueError("Package inventory differs")
    manifest_path = directory / "manifest.json"
    supplement_path = directory / "supplement.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if manifest_raw != canonical_json_bytes(manifest):
        raise ValueError("Manifest is not canonical UTF-8 JSON")
    address = manifest.pop("supplementSha256")
    addressed_leaf = directory.parent.name if directory.name == "package" else directory.name
    if address != addressed_leaf or package_address(manifest) != address:
        raise ValueError("Logical package address differs")
    supplement_raw = supplement_path.read_bytes()
    expected = [{
        "file": "supplement.json",
        "sha256": hashlib.sha256(supplement_raw).hexdigest(),
        "bytes": len(supplement_raw),
    }]
    if manifest["artifacts"] != expected:
        raise ValueError("Supplement physical bytes differ")
    document = json.loads(supplement_raw)
    if supplement_raw != canonical_json_bytes(document):
        raise ValueError("Supplement is not canonical UTF-8 JSON")
    validate_document(document)
    return {
        "address": address,
        "manifest": physical(manifest_path),
        "supplement": physical(supplement_path),
        "document": document,
    }


def publish_document(
    document: dict[str, Any], *, exchange_family_root: Path, output_root: Path
) -> dict[str, Any]:
    validate_document(document)
    supplement_raw = canonical_json_bytes(document)
    manifest_identity = {
        "schemaVersion": MANIFEST_SCHEMA,
        "contractVersion": SCHEMA,
        "supplementId": document["supplementId"],
        "kind": KIND,
        "sport": document["sport"],
        "governance": GOVERNANCE,
        "artifacts": [{
            "file": "supplement.json",
            "sha256": hashlib.sha256(supplement_raw).hexdigest(),
            "bytes": len(supplement_raw),
        }],
    }
    address = package_address(manifest_identity)
    manifest = {**manifest_identity, "supplementSha256": address}
    exchange_dir = exchange_family_root / "paper-eligibility" / "sha256" / address
    local_dir = output_root / document["sport"].lower() / "sha256" / address / "package"
    for directory in (exchange_dir, local_dir):
        immutable_bytes(directory / "supplement.json", supplement_raw)
        immutable_json(directory / "manifest.json", manifest)
        verified = verify_package(directory)
        if verified["document"] != document:
            raise ValueError("Delivered parsed document differs")
    receipt = {
        "schemaVersion": "ASP_MULTISPORT_PAPER_ELIGIBILITY_DELIVERY_V1",
        "sport": document["sport"],
        "forecastId": document["binding"]["forecastId"],
        "supplementAddress": address,
        "exchangeDirectory": str(exchange_dir.resolve()),
        "manifest": physical(exchange_dir / "manifest.json"),
        "supplement": physical(exchange_dir / "supplement.json"),
        "publicationUtc": document["publishedUtc"],
        "consumerAcknowledgement": "NOT_ESTABLISHED",
        "forecastRegenerated": False,
        "modelExecutions": 0,
        "providerRequests": 0,
        "aispWrites": 0,
        "sourceForecastAndPopulationUnchanged": True,
    }
    immutable_json(local_dir.parent / "publication-receipt.json", receipt)
    return receipt
