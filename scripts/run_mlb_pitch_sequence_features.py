"""run-mlb-pitch-sequence-features — materialize E1 free pitch-sequence process features.

Reads only registered FD1 authorities (no provider calls, no model fitting). Parses
the governed pitch-sequence encoding, builds leakage-safe batter/pitcher prior-date
process features for 2023-2025, materializes them to content-addressed runtime
storage, and registers the readiness/coverage evidence. Idempotent: an identical
authority + code revision reuses the completed materialization.
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
from server.sports_datasets.access import approved_package_root  # noqa: E402
from server.sports_datasets.consumer import SportsDatasetManifestConsumer, raw_absolute_path  # noqa: E402
from server.sports_datasets.registry import SportsDatasetRegistry  # noqa: E402
from server.sports_phase4.participation_features import _read_family  # noqa: E402
from server.sports_phase4 import pitch_sequence_features as psf  # noqa: E402
from server.sports_phase4 import pitch_sequence_run as run  # noqa: E402

DEFAULT_DB = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "persistence" / "asp_model_studio.db"
DEFAULT_DYNAMIC_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
OUTPUT_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-phase4" / "pitch-sequence-features"
CONTRACT_PATH = REPOSITORY_ROOT / "docs" / "contracts" / "MLB_PITCH_SEQUENCE_PROCESS_FEATURES_V1.md"
_STARTED = time.monotonic()
_PS_COLUMNS = ("season", "game_date", "batter_id", "pitcher_id", "source_pitch_sequence")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hb(stage: str, evidence: Mapping[str, Any]) -> None:
    print(f"[pitch-seq] {int(time.monotonic() - _STARTED):>5}s | {stage} | "
          + " ".join(f"{k}={v}" for k, v in evidence.items()), flush=True)


def _authorities(db: Database) -> tuple[dict[str, Any], dict[str, Any]]:
    reg = SportsDatasetRegistry(db)
    active = reg.get_active()
    if not active:
        raise RuntimeError("no active FD1 dataset registration")
    meta = active.get("metadata_json") or {}
    dataset_authority = {
        "registrationId": active["registration_id"],
        "datasetId": active["dataset_id"],
        "manifestSha": active["manifest_sha"],
        "partitionAuthoritySha": meta.get("partitionAuthoritySha"),
    }
    bridge_authority: dict[str, Any] = {"status": "NOT_RESOLVED"}
    try:
        from server.sports_identity_bridges.registry import SportsIdentityBridgeRegistry

        b = SportsIdentityBridgeRegistry(db).public_active()
        if isinstance(b, Mapping):
            bridge_authority = {"registrationId": b.get("registrationId"), "validationStatus": b.get("validationStatus")}
    except Exception:
        pass
    return dataset_authority, bridge_authority


def _run(args: argparse.Namespace) -> int:
    exchange_root = args.exchange_root or os.getenv("ASP_MODEL_EXCHANGE_ROOT", "")
    if not exchange_root:
        print("--exchange-root or ASP_MODEL_EXCHANGE_ROOT is required.", file=sys.stderr)
        return 2
    db_path = raw_absolute_path(Path(args.database)) if args.database else raw_absolute_path(DEFAULT_DB)
    if not db_path.exists():
        print("the initialized ASP Model Studio database is required.", file=sys.stderr)
        return 2

    db = Database(db_path)
    db.initialize()
    dataset_authority, bridge_authority = _authorities(db)
    code_revision = os.getenv("ASP_MODEL_STUDIO_CODE_REVISION", "").strip() or "worktree:pitch-sequence-e1"
    contract_sha = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() if CONTRACT_PATH.exists() else ""

    run_id = "pitch-sequence-features-" + _sha({
        "contractName": psf.FEATURE_CONTRACT_NAME, "contractSha": contract_sha,
        "parserVersion": psf.PARSER_VERSION, "datasetAuthority": dataset_authority,
        "codeRevision": code_revision,
    })[:16]
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    completed = OUTPUT_ROOT / f"{run_id}.audit.json"

    if args.status:
        print(json.dumps({"runId": run_id, "completed": completed.exists()}))
        return 0
    if completed.exists() and not args.force:
        record = json.loads(completed.read_text(encoding="utf-8"))
        _hb("REUSED_COMPLETED_MATERIALIZATION", {"runId": run_id})
        _emit(record["audit"], reused=True)
        return 0

    _hb("VALIDATING_PACKAGE", {"exchangeRoot": "configured"})
    cache = raw_absolute_path(DEFAULT_DYNAMIC_ROOT / "dataset-validation" / "validation-cache.json")
    parent = SportsDatasetManifestConsumer(approved_package_root(Path(exchange_root)), cache_path=cache, progress=None).validate()
    _hb("PACKAGE_VALIDATED", {"cacheHits": parent.cache_hits, "cacheMisses": parent.cache_misses})
    if args.preflight_only:
        _hb("PREFLIGHT_COMPLETE", {"runId": run_id})
        return 0

    seq_table, _ = _read_family(parent, "pitch_sequence", _PS_COLUMNS, progress=None)
    _hb("READ_PITCH_SEQUENCE", {"rows": seq_table.num_rows})
    seq_df = seq_table.to_pandas()

    overall_quality = psf.parse_quality(seq_df["source_pitch_sequence"])
    per_season = {
        str(int(s)): psf.parse_quality(seq_df.loc[seq_df["season"] == s, "source_pitch_sequence"])
        for s in sorted(seq_df["season"].unique())
    }
    _hb("PARSED_QUALITY", {"rate": round(overall_quality["parseSuccessRate"] or 0, 5), "unknown": overall_quality["unknownSymbols"]})

    counts = run.parse_pa_counts(seq_df)
    _hb("BUILT_PA_COUNTS", {"rows": len(counts)})
    features = run.build_features(counts)
    _hb("BUILT_FEATURES", {"targetRows": len(features), "featureCols": features.shape[1]})

    feature_cols = [c for c in features.columns if c.startswith(("batter_", "pitcher_"))]
    audit = run.compute_pitch_sequence_readiness(
        counts, features, overall_quality, per_season,
        dataset_authority=dataset_authority, identity_bridge_authority=bridge_authority,
        feature_columns=feature_cols,
    )

    # Materialize the feature matrix (content-addressed) under ignored runtime storage.
    import pyarrow as pa
    import pyarrow.parquet as pq

    feature_table = pa.Table.from_pandas(features, preserve_index=False)
    tmp_parquet = OUTPUT_ROOT / f".{run_id}.features.parquet.tmp"
    pq.write_table(feature_table, tmp_parquet, compression="zstd")
    feature_bytes = tmp_parquet.read_bytes()
    feature_sha = hashlib.sha256(feature_bytes).hexdigest()
    feature_path = OUTPUT_ROOT / f"{run_id}-features-sha256-{feature_sha[:16]}.parquet"
    os.replace(tmp_parquet, feature_path)

    audit["materializationId"] = run_id
    audit["contractSha"] = contract_sha
    audit["featureArtifact"] = {
        "logicalUri": f"asp-model-studio-runtime://sports-phase4/pitch-sequence-features/{feature_path.name}",
        "sha256": feature_sha,
        "byteCount": feature_path.stat().st_size,
        "rowCount": int(len(features)),
        "columnCount": int(features.shape[1]),
    }
    audit["rowsRead"] = int(seq_table.num_rows)
    audit["rowsMaterialized"] = int(len(features))

    audit_sha = _sha(audit)
    record = {
        "schemaVersion": "MLB_PITCH_SEQUENCE_RUNTIME_ARTIFACT_V1",
        "runId": run_id, "auditSha": audit_sha, "codeRevision": code_revision,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "audit": audit,
    }
    for pointer in (completed, OUTPUT_ROOT / "latest.audit.json"):
        tmp = pointer.with_suffix(".tmp")
        tmp.write_bytes(_canonical(record))
        os.replace(tmp, pointer)
    _hb("REGISTERED_RUNTIME_ARTIFACT", {"auditSha": audit_sha[:16], "featureSha": feature_sha[:16], "rows": len(features)})
    _emit(audit, reused=False)
    return 0


def _emit(audit: Mapping[str, Any], *, reused: bool) -> None:
    print("COMPLETED" + (" (reused)" if reused else "")
          + f" terminalStatus={audit.get('terminalStatus')}"
          + f" parseRate={round(audit.get('parseQuality', {}).get('parseSuccessRate') or 0, 5)}"
          + f" features={audit.get('totalFeatureCount')}"
          + f" rowsMaterialized={audit.get('rowsMaterialized')}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize E1 free pitch-sequence process features.")
    parser.add_argument("--exchange-root", default=os.getenv("ASP_MODEL_EXCHANGE_ROOT", ""))
    parser.add_argument("--database", default=os.getenv("ATLAS_SQLITE_PATH", ""))
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.estimate_only:
        print(json.dumps({
            "schemaVersion": "MLB_PITCH_SEQUENCE_RUNTIME_ESTIMATE_V1", "estimateOnly": True,
            "estimatedSecondsLower": 60, "estimatedSecondsUpper": 600,
            "assumptions": ["reads pitch_sequence only", "vectorized prior-date aggregation", "no model fitting"],
        }, sort_keys=True))
        return 0
    try:
        return _run(args)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
