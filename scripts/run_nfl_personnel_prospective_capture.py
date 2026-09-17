"""Run one bounded, data-only NFL personnel capture owner tick."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.sports_nfl_m1.personnel_capture import MAX_REQUESTS_PER_UTC_DAY, build_capture_plan, execute_capture
from server.sports_nfl_m1.personnel_evidence import canonical_json_bytes
from server.sports_nfl_m1.personnel_prospective import (
    CONTRACT, DEFAULT_DATA_ROOT, DEFAULT_FOUNDATION_ROOT, DEFAULT_RUNTIME_ROOT,
    OWNER_MARKER, due_slot, project_capture, requests_used_on_utc_day,
)


def args_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--foundation-root", type=Path, default=DEFAULT_FOUNDATION_ROOT)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--initial-authorized", action="store_true", help="One explicit initial capture outside normal slots.")
    parser.add_argument("--now-utc", help="Focused-test clock only; production omits it.")
    return parser


def _now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--now-utc must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _fetch(asset, conditional_headers, maximum_bytes):
    request = Request(asset.url, headers={"User-Agent": "asp-model-studio-nfl-personnel-prospective-v1", **conditional_headers})
    try:
        with urlopen(request, timeout=120) as response:
            chunks, total = [], 0
            while True:
                chunk = response.read(min(1024 * 1024, maximum_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum_bytes:
                    raise RuntimeError("streamed response exceeds remaining capture byte ceiling")
                chunks.append(chunk)
            return b"".join(chunks), {**dict(response.headers.items()), "X-ASP-HTTP-Status": str(response.status)}
    except HTTPError as error:
        if error.code == 304:
            return None, {**dict(error.headers.items()), "X-ASP-HTTP-Status": "304"}
        if error.code == 404:
            return None, {"X-ASP-HTTP-Status": "404"}
        raise


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(canonical_json_bytes(value))
    temp.replace(path)


def main(argv: list[str] | None = None) -> int:
    args = args_parser().parse_args(argv)
    now = _now(args.now_utc)
    runtime = args.runtime_root.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    rights = runtime / "RIGHTS_ACKNOWLEDGEMENT.json"
    if not args.execute:
        plan = build_capture_plan(2026, include_schedule=False)
        print(json.dumps({**plan.content(), "ownerContract": CONTRACT, "ownerMarker": OWNER_MARKER,
                          "status": "PLAN_NO_NETWORK", "dailyRequestCeiling": MAX_REQUESTS_PER_UTC_DAY,
                          "runtimeRoot": str(runtime), "dataRoot": str(args.data_root.resolve()),
                          "foundationScheduleRoot": str(args.foundation_root.resolve())}, indent=2, sort_keys=True))
        return 0
    if not rights.exists():
        raise RuntimeError("local rights acknowledgement is absent")
    ack = json.loads(rights.read_bytes())
    if ack.get("contract") != "NFL_PERSONNEL_CAPTURE_RIGHTS_ACK_V1" or not ack.get("authorized"):
        raise RuntimeError("local rights acknowledgement is invalid")

    lock = runtime / "owner.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        result = {"status": "SKIPPED_OVERLAP", "ownerMarker": OWNER_MARKER,
                  "observedAtUtc": now.isoformat().replace("+00:00", "Z")}
        _atomic_json(runtime / "LAST_RUN.json", result)
        print(json.dumps(result, sort_keys=True))
        return 0
    try:
        os.write(descriptor, f"{os.getpid()} {socket.gethostname()}\n".encode()); os.close(descriptor)
        ledger_path = runtime / "slot-ledger.json"
        ledger = json.loads(ledger_path.read_bytes()) if ledger_path.exists() else {"completedSlots": []}
        slot = "INITIAL_AUTHORIZED" if args.initial_authorized else due_slot(now, ledger.get("completedSlots", []))
        if slot is None:
            result = {"status": "NOT_DUE", "ownerMarker": OWNER_MARKER,
                      "observedAtUtc": now.isoformat().replace("+00:00", "Z"), "providerCalls": 0,
                      "AISPWrites": 0, "exchangeWrites": 0, "costUsd": 0}
            _atomic_json(runtime / "LAST_RUN.json", result)
            print(json.dumps(result, sort_keys=True))
            return 0
        plan = build_capture_plan(2026, include_schedule=False)
        used = requests_used_on_utc_day(args.data_root.resolve(), now.date().isoformat())
        if used + len(plan.assets) > MAX_REQUESTS_PER_UTC_DAY:
            result = {"status": "DAILY_BUDGET_EXHAUSTED_FAIL_CLOSED", "ownerMarker": OWNER_MARKER,
                      "observedAtUtc": now.isoformat().replace("+00:00", "Z"), "slot": slot,
                      "requestsUsedBefore": used, "providerCalls": 0, "dailyRequestCeiling": MAX_REQUESTS_PER_UTC_DAY,
                      "AISPWrites": 0, "exchangeWrites": 0, "costUsd": 0}
            _atomic_json(runtime / "LAST_RUN.json", result)
            print(json.dumps(result, sort_keys=True))
            return 0
        captured_at = now.isoformat().replace("+00:00", "Z")
        capture = execute_capture(plan, output_root=args.data_root, allow_network=True, rights_approved=True,
                                  fetcher=_fetch, captured_at_utc=captured_at)
        receipt = json.loads(Path(capture["receiptPath"]).read_bytes())
        projection = project_capture(capture_receipt=receipt, data_root=args.data_root.resolve(),
                                     foundation_root=args.foundation_root.resolve())
        if slot != "INITIAL_AUTHORIZED":
            ledger.setdefault("completedSlots", []).append(slot)
            ledger["completedSlots"] = sorted(set(ledger["completedSlots"]))
            _atomic_json(ledger_path, ledger)
        result = {"status": "BOUNDED_CAPTURE_COMPLETED", "ownerMarker": OWNER_MARKER,
                  "observedAtUtc": captured_at, "slot": slot, "providerCalls": capture["requestCount"],
                  "responseBytes": capture["responseBytes"], "newObjects": capture["newObjects"],
                  "captureReceiptPath": capture["receiptPath"], "captureReceiptSha256": capture["receiptSha256"],
                  "evidence": projection, "requestsUsedAfter": used + capture["requestCount"],
                  "dailyRequestCeiling": MAX_REQUESTS_PER_UTC_DAY, "costUsd": 0,
                  "AISPWrites": 0, "exchangeWrites": 0, "outcomeReads": 0, "modelRuns": 0,
                  "forecastPublications": 0}
        _atomic_json(runtime / "LAST_RUN.json", result)
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
