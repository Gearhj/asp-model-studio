from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.persistence.db import Database  # noqa: E402
from server.sports_datasets.access import approved_package_root  # noqa: E402
from server.sports_datasets.consumer import ManifestValidationError, SportsDatasetManifestConsumer  # noqa: E402
from server.sports_identity_bridges.consumer import (  # noqa: E402
    IdentityBridgeValidationError,
    SportsIdentityBridgeV1Consumer,
    approved_bridge_root,
)
from server.sports_identity_bridges.mlb_adapter import MLBFD1IdentityAdapter  # noqa: E402
from server.sports_identity_bridges.registry import (  # noqa: E402
    IdentityBridgeRegistrationError,
    SportsIdentityBridgeRegistry,
)


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "unavailable"
    return str(timedelta(seconds=int(max(seconds, 0)))).rjust(8, "0")


def _memory() -> str:
    try:
        import psutil

        return f"{psutil.Process().memory_info().rss / (1024**3):.2f} GiB"
    except Exception:
        return "unavailable"


def _progress(progress: Mapping[str, Any]) -> None:
    processed = progress.get("rowsProcessed", progress.get("referencesProcessed", 0))
    total = progress.get("rowsTotal", progress.get("referencesTotal", 0))
    print(
        "\n".join(
            [
                str(progress.get("title", "ASP MODEL STUDIO — MLB IDENTITY BRIDGE")),
                f"Stage: {progress.get('stage', 'UNKNOWN')}",
                f"Elapsed: {_duration(float(progress.get('elapsedSeconds', 0)))}",
                f"Files processed: {progress.get('filesProcessed', 0)} / {progress.get('filesTotal', 0)}",
                f"Partitions processed: {progress.get('partitionsProcessed', 0)} / {progress.get('partitionsTotal', 0)}",
                f"Rows or references processed: {int(processed):,} / {int(total):,}",
                f"Throughput: {int(processed) / max(float(progress.get('elapsedSeconds', 0)), 0.001):,.0f} per second",
                f"Memory: {_memory()}",
                f"Errors: {progress.get('errors', 0)}",
                f"ETA: {_duration(progress.get('etaSeconds'))}" if progress.get("etaSeconds") is not None else "ETA unavailable",
                "",
            ]
        ),
        flush=True,
    )


def _revision() -> str:
    configured = os.getenv("ASP_MODEL_STUDIO_CODE_REVISION", "").strip()
    if configured:
        return configured
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        revision = completed.stdout.strip()
        if len(revision) == 40:
            return f"git:{revision}+worktree"
    except (OSError, subprocess.SubprocessError):
        pass
    return "worktree:revision-unavailable"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate, audit, and idempotently register the approved MLB FD1 identity companion."
    )
    parser.add_argument("--exchange-root", default=os.getenv("ASP_MODEL_EXCHANGE_ROOT", ""))
    parser.add_argument("--database", default=os.getenv("ATLAS_SQLITE_PATH", ""))
    parser.add_argument(
        "--runtime-root",
        default=os.getenv("ASP_MODEL_STUDIO_SPORTS_MODELING_ROOT", ""),
    )
    parser.add_argument("--user-id", default="target-local-administrator")
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if not args.exchange_root:
        print("--exchange-root or ASP_MODEL_EXCHANGE_ROOT is required.", file=sys.stderr)
        return 2
    if not args.database:
        print("--database or ATLAS_SQLITE_PATH is required.", file=sys.stderr)
        return 2
    runtime_root = Path(args.runtime_root) if args.runtime_root else REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
    try:
        database = Database(args.database)
        database.initialize()
        registry = SportsIdentityBridgeRegistry(database)
        registry.require_parent_binding()
        exchange_root = Path(args.exchange_root)
        parent = SportsDatasetManifestConsumer(
            approved_package_root(exchange_root),
            cache_path=runtime_root / "dataset-validation" / "validation-cache.json",
            progress=_progress,
        ).validate()
        bridge = SportsIdentityBridgeV1Consumer(
            approved_bridge_root(exchange_root),
            progress=_progress,
        ).validate()
        audit = MLBFD1IdentityAdapter(bridge, parent, progress=_progress).build_join_audit()
        if args.validate_only:
            print(
                "VALID "
                f"bridge_manifest={bridge.manifest['bridge_manifest_id']} "
                f"joins={audit['resolvedReferences']}/{audit['totalReferences']} "
                f"mapping_rate={audit['mappingRate']:.6f} "
                f"parent_cache_hits={parent.cache_hits} parent_cache_misses={parent.cache_misses}"
            )
            return 0
        registration = registry.register(
            bridge,
            audit,
            runtime_root=runtime_root,
            user_id=args.user_id,
            code_revision=_revision(),
        )
        print(
            "REGISTERED "
            f"registration_id={registration['registrationId']} "
            f"disposition={registration['registrationDisposition']} "
            f"join_audit={registration['joinAudit']['artifactId']} "
            f"resolved={registration['joinAudit']['resolvedReferences']}/{registration['joinAudit']['totalReferences']}"
        )
        return 0
    except (ManifestValidationError, IdentityBridgeValidationError) as exc:
        print(f"VALIDATION FAILED [{exc.code}]: {exc}", file=sys.stderr)
        return 1
    except IdentityBridgeRegistrationError as exc:
        print(f"REGISTRATION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
