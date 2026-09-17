"""Publish the immutable NFL M1 production-baseline authority handoff."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_nfl_m1.production_handoff import publish_handoff


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("time must include a timezone")
    return parsed.astimezone(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exchange-root", type=Path,
                        default=Path(r"C:\Users\james\asp-model-exchange"))
    parser.add_argument("--effective-from", type=_time, required=True,
                        help="First kickoff governed, as timezone-aware ISO-8601")
    parser.add_argument("--issued-at", type=_time,
                        help="Explicit publication clock for deterministic testing only")
    parser.add_argument("--consumer-adapter", type=Path,
                        help="Optional AISP nfl_production_handoff.py for exact compatibility verification")
    return parser


def _revision() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _verify_consumer(adapter_path: Path, raw: bytes, digest: str) -> dict:
    spec = importlib.util.spec_from_file_location("aisp_nfl_production_handoff", adapter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load consumer adapter")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    verdict = module.verify_handoff_bytes(raw, pinned_sha256=digest)
    result = verdict.as_dict()
    if not result.get("accepted") or not result.get("production_label_allowed"):
        raise RuntimeError("AISP consumer adapter refused the published handoff: " + json.dumps(result))
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    issued = args.issued_at or datetime.now(UTC)
    if args.effective_from <= issued:
        raise SystemExit("effectiveFromUtc must be prospective at publication")
    receipt = publish_handoff(
        args.exchange_root,
        effective_from_utc=args.effective_from,
        issued_at_utc=issued,
        issuer_revision=_revision(),
    )
    handoff_path = args.exchange_root / receipt["handoffPath"]
    raw = handoff_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt["handoffSha256"]:
        raise SystemExit("published handoff physical hash differs")
    receipt["canonicalJson"] = raw == canonical_json_bytes(json.loads(raw))
    if not receipt["canonicalJson"]:
        raise SystemExit("published handoff is not canonical JSON")
    if args.consumer_adapter:
        receipt["consumerVerification"] = _verify_consumer(
            args.consumer_adapter.resolve(), raw, receipt["handoffSha256"]
        )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
