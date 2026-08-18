"""run-mlb-process-interactions — materialize E2 batter x pitcher process interactions.

A lightweight, leakage-safe transform of the existing content-addressed E1
materialization (no FD1 / pitch_sequence rescan, no model fitting). Resolves and
SHA-verifies the parent E1 feature artifact, builds the bounded E2 interaction set,
audits distribution + redundancy, materializes E2 to ignored runtime storage, and
registers the readiness evidence. Idempotent: identical E1 authority + code revision
reuses the completed E2 materialization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.persistence.db import Database  # noqa: E402
from server.sports_datasets.consumer import raw_absolute_path  # noqa: E402
from server.sports_datasets.registry import SportsDatasetRegistry  # noqa: E402
from server.sports_phase4 import process_interactions_run as e2  # noqa: E402

DEFAULT_DB = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "persistence" / "asp_model_studio.db"
PHASE4_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-phase4"
E1_ROOT = PHASE4_ROOT / "pitch-sequence-features"
OUTPUT_ROOT = PHASE4_ROOT / "process-interactions"
CONTRACT_PATH = REPOSITORY_ROOT / "docs" / "contracts" / "MLB_BATTER_PITCHER_PROCESS_INTERACTIONS_V1.md"
_STARTED = time.monotonic()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hb(stage: str, evidence: Mapping[str, Any]) -> None:
    print(f"[e2-interactions] {int(time.monotonic() - _STARTED):>5}s | {stage} | "
          + " ".join(f"{k}={v}" for k, v in evidence.items()), flush=True)


def _resolve_e1() -> tuple[dict[str, Any], Path]:
    """Resolve + SHA-verify the parent E1 artifact. Never substitutes another file."""

    latest = E1_ROOT / "latest.audit.json"
    if not latest.is_file():
        raise RuntimeError("E1 materialization is required but its runtime audit is absent")
    record = json.loads(latest.read_text(encoding="utf-8"))
    audit = record.get("audit") or {}
    if audit.get("terminalStatus") != "PITCH_SEQUENCE_FEATURES_READY":
        raise RuntimeError("parent E1 is not READY; refusing to build E2")
    artifact = audit.get("featureArtifact") or {}
    expected_sha = str(artifact.get("sha256") or "")
    uri = str(artifact.get("logicalUri") or "")
    filename = uri.rsplit("/", 1)[-1]
    parquet = E1_ROOT / filename
    if not expected_sha or not parquet.is_file():
        raise RuntimeError("parent E1 feature artifact is missing or unaddressed")
    actual_sha = hashlib.sha256(parquet.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise RuntimeError("parent E1 feature artifact SHA does not match its recorded authority")
    return audit, parquet


def _run(args: argparse.Namespace) -> int:
    db_path = raw_absolute_path(Path(args.database)) if args.database else raw_absolute_path(DEFAULT_DB)
    if not db_path.exists():
        print("the initialized ASP Model Studio database is required.", file=sys.stderr)
        return 2
    db = Database(db_path)
    db.initialize()
    active = SportsDatasetRegistry(db).get_active()
    if not active:
        raise RuntimeError("no active FD1 dataset registration")

    e1_audit, e1_parquet = _resolve_e1()
    dataset_authority = dict(e1_audit.get("datasetAuthority") or {})
    # Verify the E1 dataset authority matches the currently active registration.
    if (
        dataset_authority.get("registrationId") != active["registration_id"]
        or dataset_authority.get("manifestSha") != active["manifest_sha"]
    ):
        raise RuntimeError("parent E1 dataset authority does not match the active registration")
    bridge_authority = dict(e1_audit.get("identityBridgeAuthority") or {})
    parent_e1 = {
        "materializationId": e1_audit.get("materializationId"),
        "featureArtifactSha": (e1_audit.get("featureArtifact") or {}).get("sha256"),
        "contractName": e1_audit.get("contractName"),
        "rowCount": (e1_audit.get("featureArtifact") or {}).get("rowCount"),
    }
    code_revision = os.getenv("ASP_MODEL_STUDIO_CODE_REVISION", "").strip() or "worktree:process-interactions-e2"
    contract_sha = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() if CONTRACT_PATH.exists() else ""

    run_id = "process-interactions-" + _sha({
        "contractName": e2.INTERACTION_CONTRACT_NAME, "contractSha": contract_sha,
        "parentE1": parent_e1, "datasetAuthority": dataset_authority, "codeRevision": code_revision,
    })[:16]
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    completed = OUTPUT_ROOT / f"{run_id}.audit.json"

    if args.status:
        print(json.dumps({"runId": run_id, "completed": completed.exists()}))
        return 0
    if args.preflight_only:
        _hb("PREFLIGHT_COMPLETE", {"runId": run_id, "parentE1": parent_e1["materializationId"]})
        return 0
    if completed.exists() and not args.force:
        record = json.loads(completed.read_text(encoding="utf-8"))
        _hb("REUSED_COMPLETED_MATERIALIZATION", {"runId": run_id})
        _emit(record["audit"], reused=True)
        return 0

    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    _hb("READING_PARENT_E1", {"artifact": e1_parquet.name})
    e1_df = pq.read_table(e1_parquet).to_pandas()
    _hb("BUILDING_INTERACTIONS", {"e1Rows": len(e1_df)})
    e2_df = e2.build_interactions(e1_df)
    distribution = e2.feature_distribution_audit(e2_df)
    redundancy = e2.redundancy_audit(e2_df)
    _hb("AUDITED", {"features": len(e2.FEATURE_NAMES), "highCorrPairs": len(redundancy["highCorrelationPairs"]),
                    "exactDupes": len(redundancy["exactDuplicateGroups"]), "nearConstant": len(redundancy["nearConstantFeatures"])})

    audit = e2.compute_readiness_payload(
        e2_df, distribution, redundancy,
        dataset_authority=dataset_authority, identity_bridge_authority=bridge_authority,
        parent_e1=parent_e1, rows_read=len(e1_df),
    )

    feature_table = pa.Table.from_pandas(e2_df, preserve_index=False)
    tmp = OUTPUT_ROOT / f".{run_id}.features.parquet.tmp"
    pq.write_table(feature_table, tmp, compression="zstd")
    feature_sha = hashlib.sha256(tmp.read_bytes()).hexdigest()
    feature_path = OUTPUT_ROOT / f"{run_id}-features-sha256-{feature_sha[:16]}.parquet"
    os.replace(tmp, feature_path)

    audit["materializationId"] = run_id
    audit["contractSha"] = contract_sha
    audit["featureArtifact"] = {
        "logicalUri": f"asp-model-studio-runtime://sports-phase4/process-interactions/{feature_path.name}",
        "sha256": feature_sha, "byteCount": feature_path.stat().st_size,
        "rowCount": int(len(e2_df)), "columnCount": int(e2_df.shape[1]),
    }
    audit_sha = _sha(audit)
    record = {
        "schemaVersion": "MLB_PROCESS_INTERACTIONS_RUNTIME_ARTIFACT_V1",
        "runId": run_id, "auditSha": audit_sha, "codeRevision": code_revision,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "audit": audit,
    }
    for pointer in (completed, OUTPUT_ROOT / "latest.audit.json"):
        t = pointer.with_suffix(".tmp")
        t.write_bytes(_canonical(record))
        os.replace(t, pointer)
    _hb("REGISTERED_RUNTIME_ARTIFACT", {"auditSha": audit_sha[:16], "featureSha": feature_sha[:16], "rows": len(e2_df)})
    _emit(audit, reused=False)
    return 0


def _emit(audit: Mapping[str, Any], *, reused: bool) -> None:
    print("COMPLETED" + (" (reused)" if reused else "")
          + f" terminalStatus={audit.get('terminalStatus')}"
          + f" features={audit.get('featureCount')}"
          + f" rowsMaterialized={audit.get('rowsMaterialized')}"
          + f" parentE1={(audit.get('parentE1') or {}).get('materializationId')}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize E2 batter x pitcher process interactions from E1.")
    parser.add_argument("--database", default=os.getenv("ATLAS_SQLITE_PATH", ""))
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.estimate_only:
        print(json.dumps({
            "schemaVersion": "MLB_PROCESS_INTERACTIONS_RUNTIME_ESTIMATE_V1", "estimateOnly": True,
            "estimatedSecondsLower": 5, "estimatedSecondsUpper": 120,
            "assumptions": ["reads the content-addressed E1 artifact only", "row-local vectorized transform", "no FD1 rescan", "no model fitting"],
        }, sort_keys=True))
        return 0
    try:
        return _run(args)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
