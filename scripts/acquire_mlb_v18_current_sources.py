"""One bounded free-source catch-up; no legacy/current pointers are mutated."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_current_statcast.mlb_v18_current_sources import (
    SOURCE_ROOT, _bytes, _store, acquire_free_daily_source,
    acquire_schedule_identity_projection, safe_day, operational_capture_day,
    authenticate_operational_receipt, OPERATIONAL_PURPOSE,
    SourceRequestTelemetry,
)


def authenticated_catalog(source_root=SOURCE_ROOT):
    """Select latest source content, retaining its earliest known capture clock."""
    histories = {}
    schedules = []
    for path in sorted((Path(source_root) / "objects/sha256").glob("*.receipt.json")):
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != path.name.split(".", 1)[0]:
            raise ValueError(f"Immutable receipt checksum mismatch: {path}")
        receipt = json.loads(payload)
        family = receipt.get("family")
        if family not in {"SCHEDULE", "STATCAST", "SCHEDULE_IDENTITIES_ONLY"}:
            continue
        if family != "SCHEDULE_IDENTITIES_ONLY":
            receipt = {**receipt, "receipt": {"path": str(path), "sha256": path.name.split(".", 1)[0], "bytes": len(payload)}}
            operational = authenticate_operational_receipt(receipt)
            operational_capture_day(receipt["day"], purpose=OPERATIONAL_PURPOSE if operational else None)
        raw_path = Path(receipt["raw"]["path"]).resolve()
        if not raw_path.is_relative_to(Path(source_root).resolve()):
            raise ValueError("Raw cache evidence escapes its authorized source root")
        raw = raw_path.read_bytes()
        if len(raw) != receipt["raw"]["bytes"] or hashlib.sha256(raw).hexdigest() != receipt["raw"]["sha256"]:
            raise ValueError("Immutable raw cache evidence checksum mismatch")
        receipt = {**receipt, "sourceIdentity": path.name.split(".", 1)[0],
                   "receipt": {"path": str(path), "sha256": path.name.split(".", 1)[0], "bytes": len(payload)}}
        if family == "SCHEDULE_IDENTITIES_ONLY":
            schedules.append(receipt)
        else:
            histories.setdefault((receipt["day"], family), []).append(receipt)
    catalog = {}
    for key, history in histories.items():
        newest = max(history, key=lambda r: (r["observedAt"], r["ingestedAt"]))
        # Re-verification of unchanged raw bytes does not advance evidence age.
        same = [r for r in history if r["raw"]["sha256"] == newest["raw"]["sha256"]]
        catalog[key] = min(same, key=lambda r: (r["observedAt"], r["ingestedAt"]))
    return catalog, schedules


def incremental_plan(days, *, correction_days=3, source_root=SOURCE_ROOT):
    if not 0 <= correction_days <= 3:
        raise ValueError("Corrections are bounded to at most the last3 completed calendar days")
    catalog, schedules = authenticated_catalog(source_root)
    corrections = set(days[-correction_days:]) if correction_days else set()
    missing = [day for day in days if any((day, family) not in catalog for family in ("SCHEDULE", "STATCAST"))]
    selected = set(corrections)
    for day in missing:
        if len(selected) >= 14:
            break
        selected.add(day)
    requests = [(day, family) for day in sorted(selected) for family in ("SCHEDULE", "STATCAST")
                if day in corrections or (day, family) not in catalog]
    combined = [catalog[(day, family)] for day in days for family in ("SCHEDULE", "STATCAST") if (day, family) in catalog]
    return {"requests": requests, "cachedReceipts": combined, "scheduleReceipts": schedules,
            "correctionDates": sorted(corrections), "pendingCatchupDates": [d for d in missing if d not in selected]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-08-28")
    parser.add_argument("--through", default="latest-completed")
    parser.add_argument("--allow-free-network", action="store_true")
    parser.add_argument("--schedule-through")
    parser.add_argument("--correction-days", type=int, default=3)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--current-pregame-source-exception", action="store_true",
                        help="Explicitly authorized NEW Aug14–27 operational sources only; never evaluation artifacts")
    parser.add_argument("--reuse-schedule-projection", action="store_true")
    args = parser.parse_args()
    purpose = OPERATIONAL_PURPOSE if args.current_pregame_source_exception else None
    start = datetime.fromisoformat(operational_capture_day(args.start, purpose=purpose)).date()
    latest_prior_date = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    through = latest_prior_date if args.through == "latest-completed" else datetime.fromisoformat(operational_capture_day(args.through, purpose=purpose)).date()
    schedule_through = args.schedule_through or (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat()
    days = [(start + timedelta(days=n)).isoformat() for n in range((through - start).days + 1)]
    if not days or start.isoformat() < ("2026-08-14" if purpose else "2026-08-28"):
        raise ValueError("Current source catalog starts after the physically sealed interval")
    for day in days: operational_capture_day(day, purpose=purpose, before=datetime.now(timezone.utc).date())
    requested_at = datetime.now(timezone.utc).isoformat()
    plan = incremental_plan(days, correction_days=args.correction_days)
    request_telemetry = SourceRequestTelemetry()
    if args.plan_only or not args.allow_free_network:
        print(json.dumps({"status": "PLAN_ONLY_NO_NETWORK_OR_WRITES", "dailyRequests": plan["requests"],
            "dailyRequestCount": len(plan["requests"]), "cachedReceiptCount": len(plan["cachedReceipts"]),
            "pendingCatchupDates": plan["pendingCatchupDates"], "correctionDates": plan["correctionDates"],
            "projectedScheduleRequest": {"startDate": "2026-03-25", "throughDate": schedule_through},
            "requestTelemetry": request_telemetry.snapshot()}, indent=2))
        return
    catalog = {(r["day"], r["family"]): r for r in plan["cachedReceipts"]}
    new_receipts, failures = [], []
    # Two public requests at most concurrently. Each fixed day/family is tried once.
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = {executor.submit(acquire_free_daily_source, day, family=family,
                   allow_free_network=args.allow_free_network, purpose=purpose,
                   request_telemetry=request_telemetry): (day, family)
                   for day, family in plan["requests"]}
        for future in as_completed(pending):
            day, family = pending[future]
            try:
                receipt = future.result()
                new_receipts.append(receipt)
                prior = catalog.get((day, family))
                if prior is None or prior["raw"]["sha256"] != receipt["raw"]["sha256"]:
                    catalog[(day, family)] = receipt
                print(json.dumps({"day": day, "family": family, "status": receipt["status"],
                                  "rawSha256": receipt.get("raw", {}).get("sha256")}), flush=True)
            except Exception as error:
                failure = {"day": day, "family": family, "errorType": type(error).__name__,
                           "error": str(error)[:500], "failedAt": datetime.now(timezone.utc).isoformat(), "retried": False}
                failures.append(failure)
                print(json.dumps(failure), flush=True)
    eligible_schedules = [r for r in plan["scheduleReceipts"] if r["startDate"] <= "2026-03-25" and r["throughDate"] >= schedule_through]
    schedule = max(eligible_schedules, key=lambda r: r["observedAt"]) if eligible_schedules else None
    try:
        refreshed = schedule if args.reuse_schedule_projection and schedule else acquire_schedule_identity_projection(start="2026-03-25", through=schedule_through,
                                                        allow_free_network=True, request_telemetry=request_telemetry)
        if schedule is None or schedule["raw"]["sha256"] != refreshed["raw"]["sha256"]:
            schedule = refreshed
    except Exception as error:
        failures.append({"family": "SCHEDULE_IDENTITIES_ONLY", "errorType": type(error).__name__,
                         "error": str(error)[:500], "retried": False})
    output = {"schemaVersion": "MLB_V18_CURRENT_SOURCE_ACQUISITION_ATTEMPT_V1", "requestedAt": requested_at,
              "completedAt": datetime.now(timezone.utc).isoformat(), "requestedDates": days,
              "receipts": [catalog[k] for k in sorted(catalog)], "failures": failures,
              "newCaptures": sorted(new_receipts, key=lambda r: (r["day"], r["family"])),
              "correctionDates": plan["correctionDates"], "pendingCatchupDates": plan["pendingCatchupDates"],
              "sourceCatalogComplete": all((day, family) in catalog for day in days for family in ("SCHEDULE", "STATCAST")),
              "reusedReceiptCount": len(catalog) - sum(catalog.get((r["day"], r["family"])) == r for r in new_receipts),
              "scheduleIdentityReceipt": schedule,
              "providerCallsAuthorized": args.allow_free_network, "paidProviderCalls": 0,
              "requestTelemetry": request_telemetry.snapshot(),
              "purpose": purpose, "operationalSourceExceptionExplicit": bool(purpose),
              "sourceRetries": 0, "legacyObjectsMutated": False, "aispWrites": 0,
              "sealedEvaluationPayloadsRequested": 0}
    print(json.dumps({"attempt": _store(_bytes(output), ".acquisition-attempt.json", SOURCE_ROOT),
                      "captured": len(new_receipts), "catalogReceipts": len(catalog), "failures": len(failures)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
