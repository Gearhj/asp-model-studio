"""Run the consumer's own byte verifier over a published Week 2 batch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_receipt", type=Path, nargs="?")
    parser.add_argument("--package", type=Path)
    parser.add_argument("--aisp-root", type=Path, default=Path(r"C:\Users\james\ai-sports-predictor"))
    args = parser.parse_args()
    sys.path.insert(0, str((args.aisp_root / "server").resolve()))
    from app.forecast_exchange.supplements import verify_supplement

    if bool(args.batch_receipt) == bool(args.package):
        raise SystemExit("Provide exactly one batch receipt or --package")
    if args.package:
        verified = verify_supplement(args.package)
        print(json.dumps({"status": "AISP_CONSUMER_VERIFIER_ACCEPTED", "packages": 1, "results": [{"eventId": verified.binding["eventId"], "address": verified.address}]}, indent=2))
        raise SystemExit(0)
    batch = json.loads(args.batch_receipt.read_bytes())
    results = []
    for row in batch["packages"]:
        verified = verify_supplement(Path(row["exchangeDirectory"]))
        if verified.address != row["supplementAddress"]:
            raise SystemExit("consumer verifier returned another address")
        results.append({"eventId": row["eventId"], "address": verified.address})
    print(json.dumps({"status": "AISP_CONSUMER_VERIFIER_ACCEPTED", "packages": len(results), "results": results}, indent=2))
