"""Read-only validator for prospective cross-game evidence records."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_shared.prospective_cross_game_evidence import (  # noqa: E402
    sha256_identity,
    validate_availability_receipt,
    validate_calibration_certificate,
    validate_post_outcome,
    validate_pre_outcome,
    validate_readiness_record,
)


def load(path: Path) -> tuple[dict, bytes]:
    physical = path.read_bytes()
    value = json.loads(physical.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON_OBJECT_REQUIRED")
    return value, physical


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", required=True, choices=["PRE_OUTCOME", "POST_OUTCOME", "AVAILABILITY", "CALIBRATION", "READINESS"])
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--pre-outcome", type=Path)
    args = parser.parse_args()
    value, physical = load(args.record)
    if args.kind == "PRE_OUTCOME":
        validated = validate_pre_outcome(value)
    elif args.kind == "CALIBRATION":
        validated = validate_calibration_certificate(value)
    elif args.kind == "READINESS":
        validated = validate_readiness_record(value)
    elif args.kind in {"POST_OUTCOME", "AVAILABILITY"}:
        if args.pre_outcome is None:
            parser.error("--pre-outcome is required for POST_OUTCOME and AVAILABILITY")
        pre, _ = load(args.pre_outcome)
        validated = (validate_post_outcome(value, pre) if args.kind == "POST_OUTCOME"
                     else validate_availability_receipt(value, pre))
    else:
        raise AssertionError("unreachable kind")
    print(json.dumps({
        "status": "VALID",
        "kind": args.kind,
        "path": str(args.record),
        "bytes": len(physical),
        "physicalSha256": hashlib.sha256(physical).hexdigest(),
        "canonicalIdentitySha256": sha256_identity(validated),
    }, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
