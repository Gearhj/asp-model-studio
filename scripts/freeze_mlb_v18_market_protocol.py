"""Freeze the private, document-defined pilot. No enrollment, database or provider access."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
OUTPUT = Path(r"C:\Users\james\asp-model-studio\outputs\mlb-v18-market-prospective-v1")


def ref(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def encode(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    if path.exists() or temporary.exists():
        raise FileExistsError(f"Refusing to replace frozen artifact: {path}")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    # Windows rename fails if the destination exists; never use replace here.
    temporary.rename(path)


def main() -> None:
    if (OUTPUT / "FROZEN.json").exists():
        raise FileExistsError("Protocol is already frozen; no overwrite or new enrollment.")
    now = datetime.now(timezone.utc)
    opening = datetime(2026, 9, 19, 4, tzinfo=timezone.utc)
    if now >= opening:
        raise ValueError("Original planned opening has passed; freeze needs a newly declared future window.")
    doc = SOURCE / "docs/mlb-v18-market-prospective-v1/PROTOCOL.md"
    schema = SOURCE / "docs/mlb-v18-market-prospective-v1/PACKET_SCHEMA.json"
    feasibility = OUTPUT / "FEASIBILITY.json"
    protocol = {
        "schema": "MLB_V18_FRESH_MARKET_PROSPECTIVE_PROTOCOL_V1",
        "status": "FROZEN_DESCRIPTIVE_PILOT_NO_ENROLLMENT_YET",
        "frozenAtUtc": now.isoformat(),
        "ruleDocument": ref(doc), "packetSchema": ref(schema),
        "feasibility": ref(feasibility), "freezeSource": ref(Path(__file__).resolve()),
        "quarantineLedgerAtFreeze": ref(Path(r"C:\Users\james\asp-model-studio\server\artifacts\governance\mlb-final-oot-quarantine-v1.json")),
        "priorV2ProtocolSha256": "291243d7abad7f972e08f7610715bf8e693a267ea37a7b6189256f98aa4a4a7b",
        "model": {
            "engine": "MLB_V18_WHOLE_GAME", "simulationCount": 5000,
            "paSha256": "44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b",
            "transitionSha256": "0e5e480f897ddefa5f9dddbc229a8a43bf29f7b81443c25ece611d9d4032b253",
            "parentBundleSha256": "a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27",
            "treatmentManifestSha256": "4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3",
            "calibration": "RETAIN_RAW_V18", "componentsChanged": False,
        },
        "window": {"openingUtc": opening.isoformat(), "closeUtc": "2026-09-28T04:00:00Z", "decisionLockMinutesBeforeStart": 15, "sealDeadlineMinutesBeforeStart": 5, "postseasonIncluded": False},
        "assessmentsUtc": ["2026-09-22T16:00:00Z", "2026-09-29T16:00:00Z", "2026-10-02T16:00:00Z"],
        "assessmentJobsInstalled": False,
        "primaryMetric": "PAIRED_HOME_WIN_LOG_LOSS_V18_MINUS_FRESH_SAME_BOOK_NO_VIG_MARKET",
        "priceMaximumAgeMinutes": 15,
        "bookRule": "LEXICOGRAPHIC_CANONICAL_BOOK_THEN_PROVIDER_AMONG_FRESH_ELIGIBLE_PAIRS",
        "fullPopulationIncludesUnknownSelection": True,
        "formalLook": False, "formalAdvancementAuthority": False,
        "providerCallsAuthorized": 0, "paidDataAuthorized": False,
        "productionChangesAuthorized": False,
        "collectionReadiness": "PENDING_CONSUMER_PREGAME_EXPORT_ACKNOWLEDGEMENT",
    }
    data = encode(protocol)
    digest = hashlib.sha256(data).hexdigest()
    obj = OUTPUT / "objects/sha256" / digest
    write_once(obj / "protocol.json", data)
    write_once(obj / "PROTOCOL.md", doc.read_bytes())
    write_once(obj / "PACKET_SCHEMA.json", schema.read_bytes())
    write_once(OUTPUT / "COLLECTION_STATUS.json", encode({
        "protocolSha256": digest, "asOfUtc": now.isoformat(),
        "status": "FROZEN_NOT_ENROLLED_CONSUMER_EXPORT_PENDING",
        "consumerAcknowledgement": None, "firstCapture": None, "enrolledGames": 0,
        "newCollectorOrAssessmentJobsInstalled": False,
        "reason": "Protocol preparation/freeze complete. No prospective evidence has been fabricated or backfilled. Separate existing-capture consumer export acknowledgement is pending.",
    }))
    write_once(OUTPUT / "FROZEN.json", encode({
        "protocolSha256": digest, "protocol": ref(obj / "protocol.json"),
        "rules": ref(obj / "PROTOCOL.md"), "packetSchema": ref(obj / "PACKET_SCHEMA.json"),
        "frozenAtUtc": now.isoformat(), "status": "FROZEN",
    }))
    print(json.dumps({"protocolSha256": digest, "frozenAtUtc": now.isoformat(), "enrolledGames": 0}))


if __name__ == "__main__":
    main()
