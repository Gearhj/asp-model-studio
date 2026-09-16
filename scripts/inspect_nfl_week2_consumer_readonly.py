"""Read-only AISP owner and exact Week 2 supplement acknowledgement check."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def immutable_json(path: Path, value: object) -> dict[str, object]:
    raw = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError(f"Immutable object differs: {path}")
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_receipt", type=Path)
    parser.add_argument("--aisp-root", type=Path, default=Path(r"C:\Users\james\ai-sports-predictor"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs/nfl-week2-paper-eligibility-20260915-v1"))
    args = parser.parse_args()
    sys.path.insert(0, str((args.aisp_root / "server").resolve()))
    from app.core.config import get_settings
    from app.db.session import engine
    from sqlalchemy import text

    batch_raw = args.batch_receipt.read_bytes()
    batch = json.loads(batch_raw)
    addresses = list(batch["packages"])
    supplement_addresses = [row["supplementAddress"] for row in addresses]
    forecast_ids = [row["forecastId"] for row in addresses]
    settings = get_settings()
    query_supplements = text(
        "SELECT supplement_sha256,event_id,forecast_id,artifact_version,imported_at "
        "FROM research_supplements WHERE supplement_sha256=ANY(:addresses) "
        "ORDER BY event_id"
    )
    query_forecasts = text(
        "SELECT forecast_id,event_id,snapshot_type,snapshot_version,available_as_of_utc "
        "FROM shadow_forecasts WHERE forecast_id=ANY(:forecast_ids) ORDER BY event_id"
    )
    query_jobs = text(
        "SELECT id,job_name,status,started_at,completed_at,error_message,result FROM ("
        "SELECT *,row_number() OVER (PARTITION BY job_name ORDER BY created_at DESC) AS rank "
        "FROM job_runs WHERE job_name=ANY(:names)) AS ranked WHERE rank=1 ORDER BY job_name"
    )
    names = [
        "generate-nfl-shadow-forecasts",
        "generate-nfl-final-pregame-forecasts",
        "import-nfl-shadow-forecast-bundle",
        "consume-model-exchange-research-artifacts",
    ]
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        supplements = [dict(row) for row in connection.execute(query_supplements, {"addresses": supplement_addresses}).mappings()]
        forecasts = [dict(row) for row in connection.execute(query_forecasts, {"forecast_ids": forecast_ids}).mappings()]
        jobs = [dict(row) for row in connection.execute(query_jobs, {"names": names}).mappings()]
        connection.rollback()
    imported = {row["supplement_sha256"] for row in supplements}
    registered_forecasts = {row["forecast_id"] for row in forecasts}
    for row in jobs:
        result = row.pop("result") or {}
        row["resultSummary"] = {key: result.get(key) for key in (
            "records", "status", "enabled", "reason", "forecasts_created", "producer_called", "snapshot_types",
            "supplements_scanned", "supplements_accepted", "supplements_rejected",
            "current_bundles", "imported_bundles", "reused_bundles",
        ) if key in result}
    receipt = {
        "schemaVersion": "ASP_NFL_WEEK2_AISP_READ_ONLY_ACK_V1",
        "observedAtUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "batchReceipt": {"path": str(args.batch_receipt.resolve()), "sha256": hashlib.sha256(batch_raw).hexdigest(), "bytes": len(batch_raw)},
        "configuration": {
            "schedulerEnabled": settings.scheduler_enabled,
            "schedulerCoreJobsEnabled": settings.scheduler_core_jobs_enabled,
            "nflShadowEnabled": settings.nfl_shadow_enabled,
            "nflShadowProducerEnabled": settings.nfl_shadow_producer_enabled,
            "modelExchangeAutoImportEnabled": settings.model_exchange_auto_import_enabled,
            "mlbV18ExchangeAutoImportEnabled": settings.mlb_v18_exchange_auto_import_enabled,
            "modelExchangeImportIntervalMinutes": settings.model_exchange_import_interval_minutes,
            "nflModelStudioRoot": settings.nfl_model_studio_root,
            "nflModelStudioPython": settings.nfl_model_studio_python,
        },
        "configuredOwner": {
            "current": "AISP scheduler asp-nfl-shadow-producer-current, daily at 05:30 scheduler time",
            "finalPregame": "AISP scheduler asp-nfl-shadow-producer-final, every 5 minutes and event-gated to T-30 through T-15",
            "import": "AISP scheduler asp-model-exchange-consumer, every configured 5 minutes because at least one exchange-import gate is enabled",
        },
        "exactForecastRegistrations": {"expected": 16, "observed": len(registered_forecasts), "allPresent": set(forecast_ids) == registered_forecasts},
        "exactSupplementImports": {"expected": 16, "observed": len(imported), "allPresent": set(supplement_addresses) == imported, "missingAddresses": sorted(set(supplement_addresses) - imported)},
        "supplements": supplements,
        "forecasts": forecasts,
        "latestJobs": jobs,
        "transactionReadOnly": True,
        "aispWrites": 0,
        "providerRequests": 0,
    }
    raw = canonical_json_bytes(receipt)
    digest = hashlib.sha256(raw).hexdigest()
    target = args.output_root / "consumer-observation/sha256" / digest / "consumer-observation.json"
    reference = immutable_json(target, receipt)
    print(json.dumps({"receipt": reference, "forecastRegistrations": receipt["exactForecastRegistrations"], "supplementImports": receipt["exactSupplementImports"], "latestJobs": jobs}, default=str, indent=2))
