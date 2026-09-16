"""Bounded, provider-free replay of the NFL successor-eligibility transaction."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_gold.nfl_shadow_exchange import (
    ASP_SPORTS_FORECAST_EXCHANGE_V1,
    derive_sports_forecast_bundle_id,
    derive_sports_game_forecast_id,
    write_nfl_2026_research_shadow_locator,
    write_sports_forecast_bundle,
)
from server.sports_nfl_m1.week2_paper_eligibility import (
    DEFAULT_AUTHORIZATION_SOURCE_PATH,
    publish_week2_successors,
)


def immutable_json(path: Path, value: object) -> dict[str, object]:
    raw = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError(f"Immutable replay receipt differs: {path}")
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness", type=Path, default=ROOT / "outputs/four-sport-operational-handoff-20260915-v1/nfl-week-2-readiness.json")
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/nfl-week2-successor-automation-v1")
    parser.add_argument("--aisp-python", type=Path, default=Path(r"C:\Users\james\ai-sports-predictor\.venv\Scripts\python.exe"))
    args = parser.parse_args()
    ledger = json.loads(args.readiness.read_bytes())
    summary = next(row for row in ledger["effectiveForecasts"] if row["eventId"] == "2026_02_DET_BUF")
    source_bundle = json.loads(Path(summary["bundle"]["path"]).read_bytes())
    forecast = dict(next(row for row in source_bundle["forecasts"] if row["forecastId"] == summary["forecastId"]))
    forecast["snapshotType"] = "FINAL_PREGAME"
    forecast["snapshotVersion"] = int(forecast["snapshotVersion"]) + 1
    forecast["forecastCutoffUtc"] = "2026-09-17T23:45:00Z"
    forecast["availableAsOfUtc"] = "2026-09-17T23:50:00Z"
    forecast["forecastId"] = derive_sports_game_forecast_id(forecast)
    bundle = {
        "schemaVersion": ASP_SPORTS_FORECAST_EXCHANGE_V1, "bundleId": "PENDING",
        "sport": "NFL", "league": "NFL", "season": 2026, "slateDate": forecast["eventDate"],
        "generatedAtUtc": "2026-09-17T23:51:00Z", "status": "RESEARCH_SHADOW",
        "researchShadowOnly": True, "modelPromotionAllowed": False,
        "executionAllowed": False, "parlaysAllowed": False, "forecasts": [forecast],
    }
    bundle["bundleId"] = derive_sports_forecast_bundle_id(bundle)
    work = args.output_root / f".replay-{uuid.uuid4().hex}"
    exchange = work / "exchange"
    exchange.mkdir(parents=True)
    try:
        published = write_sports_forecast_bundle(
            exchange, bundle,
            now_utc=lambda: datetime(2026, 9, 17, 23, 51, tzinfo=timezone.utc),
        )
        write_nfl_2026_research_shadow_locator(
            exchange, current_bundle_sha256s=[published.bundle_sha256], historical_bundle_sha256s=[],
            feature_contract_sha256=forecast["engine"]["featureContractSha256"],
            updated_at_utc="2026-09-17T23:51:00Z",
            now_utc=lambda: datetime(2026, 9, 17, 23, 51, tzinfo=timezone.utc),
        )
        first = publish_week2_successors(
            exchange_root=exchange, forecast_ids=[forecast["forecastId"]],
            output_root=work / "local", authorization_source_path=DEFAULT_AUTHORIZATION_SOURCE_PATH,
            published_utc="2026-09-17T23:52:00Z",
        )
        index_path = exchange / "nfl-labs-supplements/nfl-labs-supplement-index.json"
        first_index = index_path.read_bytes()
        package = Path(first["packages"][0]["exchangeDirectory"])
        interop = subprocess.run(
            [str(args.aisp_python), str(ROOT / "scripts/check_nfl_week2_aisp_interop.py"), "--package", str(package)],
            check=True, capture_output=True, text=True,
        )
        consumer = json.loads(interop.stdout)
        second = publish_week2_successors(
            exchange_root=exchange, forecast_ids=[forecast["forecastId"]],
            output_root=work / "local", authorization_source_path=DEFAULT_AUTHORIZATION_SOURCE_PATH,
            published_utc="2026-09-17T23:53:00Z",
        )
        if index_path.read_bytes() != first_index:
            raise ValueError("Idempotent replay changed the discovery index")
        receipt = {
            "schemaVersion": "ASP_NFL_WEEK2_SUCCESSOR_AUTOMATION_REPLAY_V1",
            "fixtureOnly": True, "providerRequests": 0, "providerObjectsConsumed": 0,
            "sportsbookRequests": 0, "aispWrites": 0, "modelExecutions": 0,
            "flow": ["FORECAST_PUBLISHED", "EXACT_SUPPLEMENT_PUBLISHED", "DISCOVERY_INDEX_UPDATED", "AISP_VERIFIER_ACCEPTED", "IDEMPOTENT_REPLAY_WROTE_NOTHING"],
            "forecast": {"eventId": forecast["eventId"], "forecastId": forecast["forecastId"], "snapshotType": forecast["snapshotType"], "snapshotVersion": forecast["snapshotVersion"], "availableAsOfUtc": forecast["availableAsOfUtc"]},
            "first": first, "consumerVerifier": consumer, "repeat": second,
            "timing": {"supplementPublishedUtc": "2026-09-17T23:52:00Z", "latestFiveMinuteImportUtc": "2026-09-17T23:57:00Z", "decisionCutoffUtc": "2026-09-18T00:00:00Z", "marginSeconds": 180, "producerCommitDeadlineUtc": "2026-09-17T23:54:00Z"},
        }
        raw = canonical_json_bytes(receipt)
        digest = hashlib.sha256(raw).hexdigest()
        reference = immutable_json(args.output_root / "sha256" / digest / "replay.json", receipt)
        print(json.dumps({"receipt": reference, "flow": receipt["flow"], "supplementAddress": first["packages"][0]["supplementAddress"]}, indent=2))
    finally:
        shutil.rmtree(work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
