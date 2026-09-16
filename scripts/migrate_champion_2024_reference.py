"""Phase 7D.5A (Workstream H) — one-time explicit migration: derive a 2024-ONLY, content-addressed champion
reference from the combined legacy experiment-metrics artifact, so the ordinary server path never opens the
combined file (which carries a sealed-2025 ``final2025`` section).

This is a MAINTENANCE command. It is NOT invoked from server startup, ordinary reads, or the ordinary suite —
only from its own focused migration test. It is idempotent (content-addressed, create-once) and copies ONLY the
2024 validation metric; it fails closed if any 2025 value would leak into the output.

Usage:  python -m scripts.migrate_champion_2024_reference [--runtime-root <root>]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes


def migrate(runtime_root: Path) -> dict:
    combined = sorted(glob.glob(
        str(runtime_root / "sports-modeling" / "mlb-pa-v1" / "objects" / "sha256" / "**" / "experiment-metrics.json"),
        recursive=True))
    if not combined:
        raise RuntimeError("no combined experiment-metrics.json found; nothing to migrate")
    for path in combined:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        for cand in payload.get("payload", {}).get("candidates", []):
            if cand.get("candidateId") != "C4":
                continue
            agg = cand.get("aggregateMetrics", {})
            val = agg.get("validation2024") or agg.get("selection2024") or {}
            if val.get("logLoss") is None:
                continue
            val2024 = {"logLoss": val.get("logLoss"), "brierScore": val.get("brierScore"),
                       "topLabelEce": val.get("topLabelEce")}
            # structural leak guard: only the 2024 validation metric is copied; no sealed-year value enters it.
            if any(str(y) in json.dumps(val2024) for y in (2025, 2026)):
                raise RuntimeError("sealed out-of-time value would leak into the 2024-only reference (fail-closed)")
            ref = {"schemaVersion": "MLB_CHAMPION_2024_REFERENCE_V1", "candidateId": "C4",
                   "sourceArtifactSha256": sha256_bytes(Path(path).read_bytes()), "val2024": val2024,
                   "note": "validation-2024 only; the sealed out-of-time section is never copied"}
            content_sha = sha256_bytes(canonical_json_bytes(ref))
            out = runtime_root / "sports-modeling" / "champion-2024-reference" / f"reference-sha256-{content_sha}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            if not out.is_file():
                tmp = out.parent / f".tmp-{content_sha[:12]}"
                tmp.write_bytes(canonical_json_bytes({**ref, "referenceSha256": content_sha}))
                import os
                os.replace(tmp, out)
            return {"written": str(out), "referenceSha256": content_sha, "val2024": ref["val2024"],
                    "sourceArtifactSha256": ref["sourceArtifactSha256"]}
    raise RuntimeError("no C4 candidate with a 2024 value in the combined artifact")


def main(argv=None) -> int:
    from server.sports_cockpit.engine import RUNTIME_ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-root", default=str(RUNTIME_ROOT))
    a = ap.parse_args(argv)
    try:
        out = migrate(Path(a.runtime_root))
    except RuntimeError as exc:
        print(f"MIGRATION FAILED: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
