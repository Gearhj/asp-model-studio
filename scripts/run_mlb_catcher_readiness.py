"""run-mlb-catcher-readiness — execute the governed catcher influence readiness audit.

Reads only the registered FD1 authorities (no provider calls, no sibling repos, no
model fitting). Reconstructs catcher identity, measures starting-catcher and
PA-level coverage, and computes strict prior-history battery / catcher-batter
sample distributions, then persists content-addressed runtime evidence and prints
the real result. Idempotent: an identical authority+code-revision reuses the
completed artifact rather than recomputing.
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
from server.sports_phase4.catcher_readiness_run import compute_catcher_readiness  # noqa: E402

DEFAULT_DB = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "persistence" / "asp_model_studio.db"
DEFAULT_DYNAMIC_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
OUTPUT_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-phase4" / "catcher-readiness"
CONTRACT_PATH = REPOSITORY_ROOT / "docs" / "contracts" / "MLB_CATCHER_INFLUENCE_READINESS_V1.md"
_STARTED = time.monotonic()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _heartbeat(stage: str, evidence: Mapping[str, Any]) -> None:
    print(
        f"[catcher-readiness] {int(time.monotonic() - _STARTED):>5}s | {stage} | "
        + " ".join(f"{k}={v}" for k, v in evidence.items()),
        flush=True,
    )


def _revision() -> str:
    configured = os.getenv("ASP_MODEL_STUDIO_CODE_REVISION", "").strip()
    return configured or "worktree:catcher-readiness"


def _authorities(db: Database) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
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
        "seasons": [s["season"] for s in (active.get("seasons_json") or [])],
    }
    identity_bridge_authority: dict[str, Any] = {"status": "NOT_RESOLVED"}
    try:
        from server.sports_identity_bridges.registry import SportsIdentityBridgeRegistry

        bridge = SportsIdentityBridgeRegistry(db).public_active()
        if isinstance(bridge, Mapping):
            identity_bridge_authority = {
                "registrationId": bridge.get("registrationId"),
                "manifestSha": bridge.get("manifestSha"),
                "aliasAuthoritySha": (bridge.get("totals") or {}) and bridge.get("aliasAuthoritySha"),
                "validationStatus": bridge.get("validationStatus"),
            }
    except Exception:
        pass
    return dataset_authority, identity_bridge_authority, dataset_authority["seasons"]


def _read_frames(parent: Any, full_schema: dict[str, set[str]]) -> tuple[Any, Any, dict[tuple[str, str], str], dict[str, set[str]]]:
    from server.sports_phase4.catcher_readiness_run import (
        _FIELDING_COLUMNS, _PA_COLUMNS, _ROLE_COLUMNS,
    )

    fielding_table, _ = _read_family(parent, "player_game_fielding", _FIELDING_COLUMNS, progress=None)
    _heartbeat("READ_FIELDING", {"rows": fielding_table.num_rows})
    pa_table, _ = _read_family(parent, "plate_appearance", _PA_COLUMNS, progress=None)
    _heartbeat("READ_PLATE_APPEARANCE", {"rows": pa_table.num_rows})
    role_table, _ = _read_family(parent, "starter_usage", _ROLE_COLUMNS, progress=None)
    _heartbeat("READ_STARTER_USAGE", {"rows": role_table.num_rows})

    fielding_df = fielding_table.to_pandas()
    pa_df = pa_table.to_pandas()
    role_df = role_table.to_pandas()
    role_map = {
        (str(r.game_id), str(r.player_id)): str(r.pitcher_role)
        for r in role_df.itertuples(index=False)
        if str(getattr(r, "pitcher_role", "")).upper() in {"STARTER", "RELIEVER"}
    }
    # Availability is assessed against the FULL registered family schema (not the
    # projected read columns), so a field that exists but was not read is not
    # mislabeled UNAVAILABLE.
    return fielding_df, pa_df, role_map, full_schema


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
    dataset_authority, bridge_authority, seasons = _authorities(db)
    reg = SportsDatasetRegistry(db)
    rid = dataset_authority["registrationId"]
    full_schema = {
        family: {str(f["name"]) for f in (reg.get_schema(rid, family) or {}).get("fields_json", [])}
        for family in ("player_game_fielding", "plate_appearance")
    }
    code_revision = _revision()
    contract_sha = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() if CONTRACT_PATH.exists() else ""

    run_identity = {
        "contractName": "MLB_CATCHER_INFLUENCE_READINESS_V1",
        "contractSha": contract_sha,
        "datasetAuthority": dataset_authority,
        "identityBridgeAuthority": bridge_authority,
        "codeRevision": code_revision,
    }
    run_id = "catcher-readiness-" + _sha(run_identity)[:16]
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    completed_path = OUTPUT_ROOT / f"{run_id}.audit.json"

    if args.status:
        print(json.dumps({"runId": run_id, "completed": completed_path.exists(), "path": str(completed_path)}))
        return 0

    # Idempotent reuse: identical authority + code revision -> reuse artifact.
    if completed_path.exists() and not args.force:
        existing = json.loads(completed_path.read_text(encoding="utf-8"))
        _heartbeat("REUSED_COMPLETED_AUDIT", {"runId": run_id})
        _emit_summary(existing["audit"], reused=True)
        return 0

    _heartbeat("VALIDATING_PACKAGE", {"exchangeRoot": "configured"})
    cache_path = raw_absolute_path(DEFAULT_DYNAMIC_ROOT / "dataset-validation" / "validation-cache.json")
    parent = SportsDatasetManifestConsumer(
        approved_package_root(Path(exchange_root)),
        cache_path=cache_path,
        progress=None,
    ).validate()
    _heartbeat("PACKAGE_VALIDATED", {"cacheHits": parent.cache_hits, "cacheMisses": parent.cache_misses})

    if args.preflight_only:
        _heartbeat("PREFLIGHT_COMPLETE", {"runId": run_id})
        return 0

    fielding_df, pa_df, role_map, available = _read_frames(parent, full_schema)
    _heartbeat("COMPUTING_AUDIT", {"paRows": len(pa_df), "fieldingRows": len(fielding_df)})
    audit, _decision = compute_catcher_readiness(
        fielding_df, pa_df, role_map,
        dataset_authority=dataset_authority,
        identity_bridge_authority=bridge_authority,
        available_field_names=available,
    )
    payload = audit.to_registry_payload(run_id=run_id, contract_sha=contract_sha)
    audit_sha = _sha(payload)
    record = {
        "schemaVersion": "MLB_CATCHER_READINESS_RUNTIME_ARTIFACT_V1",
        "runId": run_id,
        "auditSha": audit_sha,
        "codeRevision": code_revision,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "audit": payload,
    }
    content_path = OUTPUT_ROOT / f"{run_id}-sha256-{audit_sha[:16]}.audit.json"
    tmp = content_path.with_suffix(".tmp")
    tmp.write_bytes(_canonical(record))
    os.replace(tmp, content_path)
    # Stable per-run pointer + a `latest` pointer the frontend projection reads.
    for pointer in (completed_path, OUTPUT_ROOT / "latest.audit.json"):
        tmp2 = pointer.with_suffix(".tmp")
        tmp2.write_bytes(_canonical(record))
        os.replace(tmp2, pointer)
    _heartbeat("REGISTERED_RUNTIME_ARTIFACT", {"auditSha": audit_sha, "path": content_path.name})
    _emit_summary(payload, reused=False)
    return 0


def _emit_summary(payload: Mapping[str, Any], *, reused: bool) -> None:
    decision = payload.get("decision", {})
    print("COMPLETED" + (" (reused)" if reused else "")
          + f" terminalStatus={payload.get('terminalStatus')}"
          + f" seasons={payload.get('seasons')}"
          + f" startingRate={decision.get('startingCatcherCoverageRate')}"
          + f" paRate={decision.get('paAssignmentCoverageRate')}",
          flush=True)


def _estimate() -> dict[str, Any]:
    return {
        "schemaVersion": "MLB_CATCHER_READINESS_RUNTIME_ESTIMATE_V1",
        "estimateOnly": True,
        "estimatedSecondsLower": 60,
        "estimatedSecondsUpper": 900,
        "assumptions": [
            "reads player_game_fielding, plate_appearance, starter_usage only",
            "vectorized prior-history counting (no per-row Python loop)",
            "no model fitting, no provider calls",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    from scripts._retired_2025_guard import retire_2025  # Phase 7D.4 Gate 12 (B8)
    retire_2025()   # opens sealed-2025 PA/fielding rows on ordinary run -> exit before any data open
    parser = argparse.ArgumentParser(description="Execute the governed MLB catcher influence readiness audit.")
    parser.add_argument("--exchange-root", default=os.getenv("ASP_MODEL_EXCHANGE_ROOT", ""))
    parser.add_argument("--database", default=os.getenv("ATLAS_SQLITE_PATH", ""))
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--force", action="store_true", help="recompute even if a completed artifact exists")
    args = parser.parse_args(argv)
    if args.estimate_only:
        print(json.dumps(_estimate(), sort_keys=True))
        return 0
    try:
        return _run(args)
    except Exception as exc:  # noqa: BLE001 - surface the exact blocker, do not fabricate
        print(f"FAILED {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
