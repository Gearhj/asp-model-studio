"""Freeze the predeclared V18 prospective evaluation-contract supplement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast.mlb_v18_acceptance_protocol import PROTOCOL, protocol_sha256


def main() -> int:
    checksum = protocol_sha256()
    target = ROOT / "outputs/mlb-v18-acceptance-protocol/sha256" / checksum
    target.mkdir(parents=True, exist_ok=True)
    (target / "evaluation-contract.json").write_bytes(canonical_json_bytes(PROTOCOL))
    source = ROOT / "server/sports_current_statcast/mlb_v18_acceptance_protocol.py"
    evaluator = ROOT / "scripts/evaluate_mlb_v18_acceptance_protocol.py"
    files = []
    for path in (source, evaluator):
        raw = path.read_bytes()
        files.append({
            "relativePath": path.relative_to(ROOT).as_posix(), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    manifest = {
        "schemaVersion": "MLB_V18_EVALUATION_CONTRACT_SUPPLEMENT_MANIFEST_V1",
        "contractId": f"mlb-v18-acceptance-{checksum[:24]}",
        "contractSha256": checksum,
        "referencedBundleSha256": PROTOCOL["referencedBundle"]["bundleSha256"],
        "verdict": PROTOCOL["verdict"], "implementationFiles": files,
        "lineage": PROTOCOL["lineage"],
    }
    (target / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    latest = {
        "contractId": manifest["contractId"], "contractSha256": checksum,
        "relativePath": target.relative_to(ROOT).as_posix(),
    }
    latest_path = ROOT / "outputs/mlb-v18-acceptance-protocol/latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_bytes(canonical_json_bytes(latest))
    reloaded = json.loads((target / "evaluation-contract.json").read_text(encoding="utf-8"))
    if hashlib.sha256(canonical_json_bytes(reloaded)).hexdigest() != checksum:
        raise RuntimeError("evaluation contract reload checksum differs")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
