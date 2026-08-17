from __future__ import annotations

import argparse
import hashlib
import os
import stat
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.persistence.db import Database  # noqa: E402
from server.sports_datasets.access import approved_package_root  # noqa: E402
from server.sports_datasets.consumer import (  # noqa: E402
    SportsDatasetManifestConsumer,
    raw_absolute_path,
    reject_reparse_chain,
)
from server.sports_identity_bridges.consumer import (  # noqa: E402
    SportsIdentityBridgeV1Consumer,
    approved_bridge_root,
)
from server.sports_identity_bridges.registry import SportsIdentityBridgeRegistry  # noqa: E402
from server.sports_modeling.registry import SportsPAResearchRegistry  # noqa: E402
from server.sports_modeling.runner import run_mlb_pa_research  # noqa: E402


EXPECTED_BRIDGE_REGISTRATION_ID = "sports-identity-bridge-6b69e7dcf4c5db76"
EXPECTED_BRIDGE_MANIFEST_SHA = "6b69e7dcf4c5db7615420ee9f6f6f797b0335e31ab475646291f3a4cf90c52cf"
PROJECT_ID = "sports-project-mlb-fd1-1b58d5d1def2"


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
        if len(revision) == 40 and all(character in "0123456789abcdef" for character in revision):
            tracked = subprocess.run(
                ["git", "diff", "--no-ext-diff", "--binary", "HEAD", "--"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout
            untracked_output = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout
            untracked = sorted(path for path in untracked_output.split(b"\0") if path)
            if not tracked and not untracked:
                return f"git:{revision}"

            digest = hashlib.sha256()
            digest.update(b"ASP_MODEL_STUDIO_WORKTREE_V1\0")
            digest.update(revision.encode("ascii"))
            digest.update(len(tracked).to_bytes(8, "big"))
            digest.update(tracked)
            for encoded_path in untracked:
                relative_path = Path(os.fsdecode(encoded_path))
                physical_path = (REPOSITORY_ROOT / relative_path).resolve()
                physical_path.relative_to(REPOSITORY_ROOT)
                metadata = physical_path.lstat()
                digest.update(len(encoded_path).to_bytes(4, "big"))
                digest.update(encoded_path)
                digest.update(stat.S_IFMT(metadata.st_mode).to_bytes(4, "big"))
                if stat.S_ISLNK(metadata.st_mode):
                    content = os.readlink(physical_path).encode("utf-8")
                elif stat.S_ISREG(metadata.st_mode):
                    content = physical_path.read_bytes()
                else:
                    raise RuntimeError(f"Unsupported untracked worktree entry: {relative_path}")
                digest.update(len(content).to_bytes(8, "big"))
                digest.update(content)
            return f"git:{revision}+worktree-sha256:{digest.hexdigest()}"
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "Unable to derive content-bound source provenance; set "
            "ASP_MODEL_STUDIO_CODE_REVISION explicitly"
        ) from exc
    raise RuntimeError(
        "Unable to derive content-bound source provenance; set "
        "ASP_MODEL_STUDIO_CODE_REVISION explicitly"
    )


def _validate_isolated_database_file(path: Path, *, label: str) -> None:
    reject_reparse_chain(path, label=label)
    if not path.exists():
        return
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RuntimeError("The isolated ASP Model Studio database must be a single-link regular file")


def _package_progress(progress: Mapping[str, Any]) -> None:
    _model_progress(str(progress.get("stage", "PACKAGE_VALIDATION")), progress)


def _model_progress(stage: str, evidence: Mapping[str, Any]) -> None:
    elapsed = float(evidence.get("elapsedSeconds", 0.0) or 0.0)
    processed = int(
        evidence.get(
            "rowsProcessed",
            evidence.get("referencesProcessed", evidence.get("partitionsProcessed", 0)),
        )
        or 0
    )
    total = int(
        evidence.get(
            "rowsTotal",
            evidence.get("referencesTotal", evidence.get("partitionsTotal", 0)),
        )
        or 0
    )
    season_or_fold = evidence.get(
        "season",
        evidence.get(
            "currentSeason",
            evidence.get("validationSeason", evidence.get("foldId", "not applicable")),
        ),
    )
    lines = [
        "ASP MODEL STUDIO — MLB PA RESEARCH BASELINE",
        f"Stage: {stage}",
        f"Elapsed: {_duration(elapsed)}",
        f"Season or fold: {season_or_fold}",
        f"Candidate: {evidence.get('candidateId', 'not applicable')}",
        f"Rows processed: {processed:,} / {total:,}",
        f"Throughput: {processed / max(elapsed, 0.001):,.0f} rows or references per second",
        f"Memory: {_memory()}",
        f"Errors: {evidence.get('errors', 0)}",
        f"ETA: {_duration(evidence.get('etaSeconds'))}" if evidence.get("etaSeconds") is not None else "ETA unavailable",
        "",
    ]
    print("\n".join(lines), flush=True)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize and register the bounded MLB plate-appearance research baseline."
    )
    parser.add_argument("--exchange-root", default=os.getenv("ASP_MODEL_EXCHANGE_ROOT", ""))
    parser.add_argument("--database", default=os.getenv("ATLAS_SQLITE_PATH", ""))
    parser.add_argument(
        "--runtime-root",
        default=os.getenv("ASP_MODEL_STUDIO_SPORTS_MODELING_ROOT", ""),
    )
    parser.add_argument("--user-id", default="target-local-administrator")
    parser.add_argument("--bootstrap-replicates", type=int, default=500)
    parser.add_argument("--bootstrap-seed", type=int, default=20_260_817)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if not args.exchange_root:
        print("--exchange-root or ASP_MODEL_EXCHANGE_ROOT is required.", file=sys.stderr)
        return 2
    if not args.database:
        print("--database or ATLAS_SQLITE_PATH is required.", file=sys.stderr)
        return 2
    if args.bootstrap_replicates < 2:
        print("--bootstrap-replicates must be at least two.", file=sys.stderr)
        return 2

    approved_database = raw_absolute_path(
        REPOSITORY_ROOT
        / ".runtime"
        / "asp-model-studio"
        / "persistence"
        / "asp_model_studio.db"
    )
    requested_database = raw_absolute_path(Path(args.database))
    if requested_database != approved_database:
        print("--database must be the isolated ASP Model Studio database.", file=sys.stderr)
        return 2
    try:
        _validate_isolated_database_file(
            requested_database,
            label="Configured ASP Model Studio database chain",
        )
    except Exception as exc:
        print(f"--database is unsafe: {exc}", file=sys.stderr)
        return 2
    if requested_database.resolve(strict=False) != approved_database.resolve(strict=False):
        print("--database must resolve to the isolated ASP Model Studio database.", file=sys.stderr)
        return 2

    requested_runtime_root = (
        Path(args.runtime_root)
        if args.runtime_root
        else REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
    )
    approved_runtime_root = raw_absolute_path(
        REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
    )
    requested_runtime_root = raw_absolute_path(requested_runtime_root)
    if requested_runtime_root != approved_runtime_root:
        print("--runtime-root must be the repository-owned ignored sports-modeling root.", file=sys.stderr)
        return 2
    try:
        reject_reparse_chain(
            requested_runtime_root,
            label="Configured sports-modeling runtime root chain",
        )
    except Exception as exc:
        print(f"--runtime-root is unsafe: {exc}", file=sys.stderr)
        return 2
    if requested_runtime_root.resolve(strict=False) != approved_runtime_root.resolve(strict=False):
        print("--runtime-root must resolve to the repository-owned sports-modeling root.", file=sys.stderr)
        return 2
    runtime_root = requested_runtime_root
    started = time.monotonic()
    try:
        database = Database(requested_database)
        database.initialize()
        _validate_isolated_database_file(
            requested_database,
            label="Initialized ASP Model Studio database chain",
        )
        registered_bridge = SportsIdentityBridgeRegistry(database).public_active()
        if (
            not registered_bridge
            or registered_bridge.get("registrationId") != EXPECTED_BRIDGE_REGISTRATION_ID
            or registered_bridge.get("manifestSha") != EXPECTED_BRIDGE_MANIFEST_SHA
            or registered_bridge.get("validationStatus") != "PASS"
            or registered_bridge.get("joinAudit", {}).get("status") != "PASS"
        ):
            raise RuntimeError("The exact active identity-bridge registration is required before modeling")
        join_audit_id = str(registered_bridge.get("joinAudit", {}).get("artifactId", ""))
        if not join_audit_id.startswith("sports-identity-join-audit:sha256:"):
            raise RuntimeError("The persisted exact identity join-audit ID is required before modeling")

        exchange_root = Path(args.exchange_root)
        parent = SportsDatasetManifestConsumer(
            approved_package_root(exchange_root),
            cache_path=runtime_root / "dataset-validation" / "validation-cache.json",
            progress=_package_progress,
        ).validate()
        bridge = SportsIdentityBridgeV1Consumer(
            approved_bridge_root(exchange_root),
            progress=_package_progress,
        ).validate()
        payload = run_mlb_pa_research(
            project_id=PROJECT_ID,
            parent=parent,
            identity_bridge=bridge,
            join_audit_id=join_audit_id,
            runtime_root=runtime_root,
            code_revision=_revision(),
            bootstrap_replicates=args.bootstrap_replicates,
            bootstrap_seed=args.bootstrap_seed,
            progress=_model_progress,
        )
        registered = SportsPAResearchRegistry(database).register(
            payload,
            user_id=args.user_id,
        )
        baseline = registered["paBaseline"]
        registry = baseline["registry"]
        decision = baseline["decision"]
        print(
            "COMPLETED "
            f"run_id={baseline['run']['runId']} "
            f"feature_view_id={baseline['featureView']['featureViewId']} "
            f"selected_candidate={baseline['selected']['candidateId']} "
            f"terminal_status={decision['terminalStatus']} "
            f"disposition={registry['registrationDisposition']} "
            f"elapsed={_duration(time.monotonic() - started)}",
            flush=True,
        )
        return 0
    except Exception as exc:
        print(f"MLB PA BASELINE FAILED [{type(exc).__name__}]: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
