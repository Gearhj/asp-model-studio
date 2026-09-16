"""Freeze the V2 acceptance protocol and exploratory-cohort contract supplement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast.mlb_bet_readiness_cohort import EXPORT_CONTRACT, export_contract_sha256
from server.sports_current_statcast.mlb_v18_acceptance_protocol_v2 import (
    PREDECESSOR_SHA256, PROTOCOL, protocol_sha256,
)


COHORT_SHA256 = "cd44ef70d6d4a5f3258cfad2cd6222accc5a39431d131184cf7b851ecced5785"


def main() -> int:
    checksum = protocol_sha256()
    target = ROOT / "outputs/mlb-v18-acceptance-protocol-v2/sha256" / checksum
    target.mkdir(parents=True, exist_ok=True)
    (target / "evaluation-contract.json").write_bytes(canonical_json_bytes(PROTOCOL))
    (target / "bet-readiness-export-contract.json").write_bytes(canonical_json_bytes(EXPORT_CONTRACT))
    implementation = []
    for relative in (
        "server/sports_current_statcast/mlb_v18_acceptance_protocol_v2.py",
        "server/sports_current_statcast/mlb_bet_readiness_cohort.py",
        "scripts/evaluate_mlb_v18_acceptance_protocol_v2.py",
        "scripts/export_aisp_gen1_bet_readiness_read_only.py",
        "scripts/build_mlb_gen1_bet_readiness_cohort.py",
    ):
        path = ROOT / relative
        raw = path.read_bytes()
        implementation.append({"relativePath": relative, "bytes": len(raw),
                               "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {
        "schemaVersion": "MLB_V18_EVALUATION_CONTRACT_SUPPLEMENT_MANIFEST_V2",
        "contractId": f"mlb-v18-acceptance-v2-{checksum[:24]}",
        "contractSha256": checksum,
        "predecessorProtocolSha256": PREDECESSOR_SHA256,
        "referencedBundleSha256": PROTOCOL["referencedBundle"]["bundleSha256"],
        "betReadinessExportContractSha256": export_contract_sha256(),
        "descriptiveCohortSha256": COHORT_SHA256,
        "verdict": PROTOCOL["verdict"], "implementationFiles": implementation,
        "lineage": {"predecessorModified": False, "acceptedBundleModified": False,
                    "finalOotAccessed": False, "newModelFit": False,
                    "aispRowsModified": 0, "providerCalls": 0},
    }
    (target / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    latest = {"contractId": manifest["contractId"], "contractSha256": checksum,
              "predecessorProtocolSha256": PREDECESSOR_SHA256,
              "relativePath": target.relative_to(ROOT).as_posix()}
    latest_path = ROOT / "outputs/mlb-v18-acceptance-protocol-v2/latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_bytes(canonical_json_bytes(latest))
    reloaded = json.loads((target / "evaluation-contract.json").read_text(encoding="utf-8"))
    if hashlib.sha256(canonical_json_bytes(reloaded)).hexdigest() != checksum:
        raise RuntimeError("V2 evaluation-contract reload checksum differs")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
