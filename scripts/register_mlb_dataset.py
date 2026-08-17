from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.persistence.db import Database  # noqa: E402
from server.sports_datasets.access import approved_package_root  # noqa: E402
from server.sports_datasets.consumer import ManifestValidationError, SportsDatasetManifestConsumer  # noqa: E402
from server.sports_datasets.registry import SportsDatasetRegistry  # noqa: E402


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "unavailable"
    value = int(max(seconds, 0))
    return str(timedelta(seconds=value)).rjust(8, "0")


def _memory() -> str:
    try:
        import psutil

        gib = psutil.Process().memory_info().rss / (1024**3)
        return f"{gib:.2f} GiB"
    except Exception:
        return "unavailable"


def _print_progress(progress: dict[str, Any]) -> None:
    print(
        "\n".join(
            [
                progress["title"],
                f"Stage: {progress['stage']}",
                f"Elapsed: {_duration(progress['elapsedSeconds'])}",
                f"Partitions processed: {progress['partitionsProcessed']} / {progress['partitionsTotal']}",
                f"Rows processed: {progress['rowsProcessed']:,} / {progress['rowsTotal']:,}",
                f"Memory: {_memory()}",
                f"Errors: {progress['errors']}",
                f"ETA: {_duration(progress['etaSeconds'])}" if progress["etaSeconds"] is not None else "ETA unavailable",
                "",
            ]
        ),
        flush=True,
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and register the approved immutable MLB FD1 exchange package.")
    parser.add_argument("--validate-only", action="store_true", help="Validate without writing registration metadata.")
    parser.add_argument("--exchange-root", default=os.getenv("ASP_MODEL_EXCHANGE_ROOT", ""), help="Administrator-controlled neutral exchange root.")
    parser.add_argument("--database", default=os.getenv("ATLAS_SQLITE_PATH", ""), help="Target-local ASP Model Studio SQLite database.")
    parser.add_argument("--cache", default="", help="Ignored target-local validation cache path.")
    parser.add_argument("--user-id", default="target-local-administrator", help="Registering target-local user identity.")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if not args.exchange_root:
        print("ASP_MODEL_EXCHANGE_ROOT is required.", file=sys.stderr)
        return 2
    runtime_root = Path(
        os.getenv("ASP_MODEL_STUDIO_SPORTS_MODELING_ROOT", "")
        or REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
    )
    cache_path = Path(args.cache) if args.cache else runtime_root / "dataset-validation" / "validation-cache.json"
    package_root = approved_package_root(Path(args.exchange_root))
    try:
        validated = SportsDatasetManifestConsumer(package_root, cache_path=cache_path, progress=_print_progress).validate()
        if args.validate_only:
            print(
                f"VALID manifest={validated.manifest['manifest_id']} "
                f"authority={validated.partition_authority_sha} "
                f"cache_hits={validated.cache_hits} cache_misses={validated.cache_misses}"
            )
            return 0
        if not args.database:
            print("--database or ATLAS_SQLITE_PATH is required for registration.", file=sys.stderr)
            return 2
        database = Database(args.database)
        database.initialize()
        registry = SportsDatasetRegistry(database)
        registration = registry.register(validated, user_id=args.user_id)
        print(
            f"REGISTERED registration_id={registration['registration_id']} "
            f"project_id=sports-project-mlb-fd1-{validated.manifest['manifest_sha256'][:12]} "
            f"cache_hits={validated.cache_hits} cache_misses={validated.cache_misses}"
        )
        return 0
    except ManifestValidationError as exc:
        print(f"VALIDATION FAILED [{exc.code}]: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
