from __future__ import annotations

import argparse
import hashlib
import os
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Callable, Mapping
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.sports_datasets.access import approved_package_root  # noqa: E402
from server.sports_datasets.constants import EXPECTED_TOTALS, PROJECT_ID  # noqa: E402
from server.sports_datasets.consumer import (  # noqa: E402
    SportsDatasetManifestConsumer,
    raw_absolute_path,
    reject_reparse_chain,
)
from server.sports_identity_bridges.consumer import (  # noqa: E402
    SportsIdentityBridgeV1Consumer,
    approved_bridge_root,
)
from server.persistence.db import Database  # noqa: E402
from server.sports_phase4.dynamic_contract import (  # noqa: E402
    PHASE3_FEATURE_CONTRACT_SHA,
    PHASE3_FEATURE_VIEW_ID,
    PHASE3_RUN_ID,
    PHASE3_RUN_SHA,
)
from server.sports_phase4.dynamic_runner import (  # noqa: E402
    load_phase3_runtime_inputs,
    run_mlb_dynamic_player_state,
)
from server.sports_phase4.registry import (  # noqa: E402
    PHASE3_EXPERIMENT_ID,
    PHASE3_FEATURE_CONTRACT_NAME,
    PHASE3_GRAPH_ID,
    SportsPhase4Registry,
    build_phase4_study_payload,
)
from server.sports_phase4.supervision import (  # noqa: E402
    SupervisedWorkerResult,
    SupervisionError,
    SupervisionLimits,
    WorkerEventEmitter,
    is_supervised_worker,
    run_supervised_worker,
    supervised_worker_environment,
)


MILESTONE_NAME = "Milestone A"
COMPONENT_NAME = "Dynamic Player State"
DATASET_VALIDATION_CACHE_RELATIVE = Path("dataset-validation") / "validation-cache.json"
SUPERVISED_WORKER_ARGUMENT = "--supervised-worker"
DYNAMIC_STAGE_LIMITS: dict[str, float] = {
    "TUNING_DYNAMIC_LOGISTIC_2023": 90.0 * 60.0,
    "FITTING_DYNAMIC_2023_VALIDATING_2024": 90.0 * 60.0,
    "REFITTING_DYNAMIC_THROUGH_2024_VALIDATING_2025": 90.0 * 60.0,
}
DYNAMIC_SUPERVISION_LIMITS = SupervisionLimits(
    overall_seconds=8.0 * 60.0 * 60.0,
    silence_seconds=90.0,
    rss_bytes=8 * 1024**3,
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
        if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
            raise RuntimeError("git revision is not canonical")
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
        digest.update(b"ASP_MODEL_STUDIO_DYNAMIC_WORKTREE_V1\0")
        digest.update(revision.encode("ascii"))
        digest.update(len(tracked).to_bytes(8, "big"))
        digest.update(tracked)
        for encoded_path in untracked:
            relative = Path(os.fsdecode(encoded_path))
            physical = raw_absolute_path(REPOSITORY_ROOT / relative)
            physical.relative_to(REPOSITORY_ROOT)
            reject_reparse_chain(physical, label="Code revision input chain")
            metadata = physical.lstat()
            digest.update(len(encoded_path).to_bytes(4, "big"))
            digest.update(encoded_path)
            digest.update(stat.S_IFMT(metadata.st_mode).to_bytes(4, "big"))
            if stat.S_ISLNK(metadata.st_mode):
                content = os.readlink(physical).encode("utf-8")
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                content = physical.read_bytes()
            else:
                raise RuntimeError("untracked revision input must be a single-link regular file")
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return f"git:{revision}+worktree-sha256:{digest.hexdigest()}"
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "Unable to derive content-bound source provenance; set "
            "ASP_MODEL_STUDIO_CODE_REVISION explicitly"
        ) from exc


_STARTED = time.monotonic()


def _progress(stage: str, evidence: Mapping[str, Any]) -> None:
    elapsed = float(
        evidence.get(
            "elapsedSeconds",
            evidence.get("workerElapsedSeconds", time.monotonic() - _STARTED),
        )
        or 0.0
    )
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
    throughput = (
        f"{processed / elapsed:,.0f} rows/sec"
        if processed > 0 and elapsed > 0
        else "unavailable"
    )
    eta = _duration(float(evidence["etaSeconds"])) if evidence.get("etaSeconds") is not None else "unavailable"
    print(
        "\n".join(
            [
                "ASP MODEL STUDIO — MLB DYNAMIC PLAYER STATE V1",
                f"Milestone: {MILESTONE_NAME}",
                f"Component: {COMPONENT_NAME}",
                f"Stage: {stage}",
                f"Elapsed: {_duration(elapsed)}",
                "Season or fold: "
                f"{evidence.get('validationSeason', evidence.get('currentSeason', evidence.get('foldId', 'not applicable')))}",
                f"Candidate: {evidence.get('candidateId', 'not applicable')}",
                f"Rows processed: {processed:,} / {total:,}",
                f"Throughput: {throughput}",
                f"ETA: {eta}",
                "Memory: "
                + (
                    f"{int(evidence['workerRssBytes']) / (1024**3):.2f} GiB"
                    if isinstance(evidence.get("workerRssBytes"), int)
                    and not isinstance(evidence.get("workerRssBytes"), bool)
                    else _memory()
                ),
                f"Errors: {evidence.get('errors', 0)}",
                "",
            ]
        ),
        flush=True,
    )


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the research-only MLB_DYNAMIC_PLAYER_STATE_V1 component from exact "
            "registered dataset/bridge authorities and immutable Phase 3 runtime artifacts."
        )
    )
    parser.add_argument("--exchange-root", default=os.getenv("ASP_MODEL_EXCHANGE_ROOT", ""))
    parser.add_argument("--database", default=os.getenv("ATLAS_SQLITE_PATH", ""))
    parser.add_argument(
        "--runtime-root",
        default=os.getenv("ASP_MODEL_STUDIO_SPORTS_MODELING_ROOT", ""),
    )
    parser.add_argument("--bootstrap-resamples", type=int, default=500)
    parser.add_argument("--bootstrap-seed", type=int, default=20_260_817)
    parser.add_argument("--user-id", default="target-local-administrator")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate exact exchange and Phase 3 runtime inputs without building or writing Phase 4 artifacts.",
    )
    parser.add_argument(SUPERVISED_WORKER_ARGUMENT, action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _validate_isolated_database_file(path: Path, *, label: str) -> None:
    reject_reparse_chain(path, label=label)
    if not path.exists():
        return
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RuntimeError(
            "The isolated ASP Model Studio database must be a single-link regular file"
        )


def _validated_dataset_cache_path(
    requested_runtime: Path,
    approved_runtime: Path,
) -> Path:
    validation_cache = raw_absolute_path(
        requested_runtime / DATASET_VALIDATION_CACHE_RELATIVE
    )
    expected_cache = raw_absolute_path(
        approved_runtime / DATASET_VALIDATION_CACHE_RELATIVE
    )
    if validation_cache != expected_cache:
        raise RuntimeError("dataset validation cache path differs from the governed authority")
    reject_reparse_chain(validation_cache, label="Governed dataset validation cache chain")
    if not validation_cache.is_file():
        raise RuntimeError("the warmed governed dataset validation cache is required")
    metadata = validation_cache.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RuntimeError("the governed dataset validation cache must be a single-link file")
    return validation_cache


def _worker_main(
    args: argparse.Namespace,
    *,
    progress: Callable[[str, Mapping[str, Any]], None],
) -> int:
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
    approved_runtime = raw_absolute_path(
        REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
    )
    requested_runtime = raw_absolute_path(
        Path(args.runtime_root) if args.runtime_root else approved_runtime
    )
    if requested_runtime != approved_runtime:
        print("--runtime-root must be the repository-owned ignored sports-modeling root.", file=sys.stderr)
        return 2
    try:
        reject_reparse_chain(requested_runtime, label="Configured dynamic runtime root chain")
        if requested_runtime.resolve(strict=False) != approved_runtime.resolve(strict=False):
            raise RuntimeError("runtime root resolves outside the approved boundary")
        database = Database(requested_database)
        database.initialize()
        registry = SportsPhase4Registry(database)
        # This is the first post-initialize action and precedes every exchange
        # or runtime authority read, including preflight-only execution.
        registry.validate_registered_authorities()
        _validate_isolated_database_file(
            requested_database,
            label="Initialized ASP Model Studio database chain",
        )
        exchange_root = Path(args.exchange_root)
        validation_cache = _validated_dataset_cache_path(
            requested_runtime,
            approved_runtime,
        )
        parent = SportsDatasetManifestConsumer(
            approved_package_root(exchange_root),
            cache_path=validation_cache,
            progress=lambda evidence: progress(
                str(evidence.get("stage", "PACKAGE_VALIDATION")), evidence
            ),
        ).validate()
        expected_partitions = int(EXPECTED_TOTALS["parquet_files"])
        if (
            len(parent.partitions) != expected_partitions
            or parent.cache_misses != 0
            or parent.cache_hits != len(parent.partitions)
        ):
            raise RuntimeError(
                "Milestone A requires all 329 registered parent partitions from the "
                "exact fully warmed dataset-validation cache"
            )
        progress(
            "DATASET_VALIDATION_CACHE_REUSED",
            {
                "partitionsProcessed": len(parent.partitions),
                "partitionsTotal": expected_partitions,
                "cacheHits": parent.cache_hits,
                "cacheMisses": parent.cache_misses,
                "errors": 0,
            },
        )
        bridge = SportsIdentityBridgeV1Consumer(
            approved_bridge_root(exchange_root),
            progress=lambda evidence: progress(
                str(evidence.get("stage", "BRIDGE_VALIDATION")), evidence
            ),
        ).validate()
        phase3 = load_phase3_runtime_inputs(requested_runtime)
        if args.preflight_only:
            print(
                "PREFLIGHT_COMPLETE "
                f"feature_rows={phase3.feature_table.num_rows} "
                f"d0_2024_rows={phase3.d0_folds[2024].table.num_rows} "
                f"d0_2025_rows={phase3.d0_folds[2025].table.num_rows} "
                f"cache_hits={parent.cache_hits} "
                f"cache_misses={parent.cache_misses}",
                flush=True,
            )
            return 0
        code_revision = _revision()
        result = run_mlb_dynamic_player_state(
            project_id=PROJECT_ID,
            parent=parent,
            identity_bridge=bridge,
            runtime_root=requested_runtime,
            code_revision=code_revision,
            bootstrap_resamples=args.bootstrap_resamples,
            bootstrap_seed=args.bootstrap_seed,
            progress=progress,
        )
        study = build_phase4_study_payload(
            phase3_baseline={
                "runId": PHASE3_RUN_ID,
                "runSha": PHASE3_RUN_SHA,
                "experimentId": PHASE3_EXPERIMENT_ID,
                "featureContractName": PHASE3_FEATURE_CONTRACT_NAME,
                "featureContractSha": PHASE3_FEATURE_CONTRACT_SHA,
                "featureViewId": PHASE3_FEATURE_VIEW_ID,
                "graphId": PHASE3_GRAPH_ID,
                "status": "RESEARCH_BASELINE",
            },
            dynamic_state=result["component"],
            artifacts=result["artifacts"],
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            code_revision=code_revision,
        )
        saved = registry.register(study, user_id=args.user_id)
        component = result["component"]
        registered_component = saved["phase4"]["components"]["dynamicState"]
        print(
            "COMPLETED "
            f"component_id={registered_component['componentId']} "
            f"selected={component['selected']['candidateId']} "
            f"decision={component['decision']['decision']} "
            f"artifacts={len(result['artifacts'])} "
            f"study_id={saved['phase4']['studyId']} "
            f"graph_id={saved['phase4']['graph']['graphId']}",
            flush=True,
        )
        return 0
    except Exception as exc:
        print(f"FAILED {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


def _supervise(argv: list[str]) -> SupervisedWorkerResult:
    command = [
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        *argv,
        SUPERVISED_WORKER_ARGUMENT,
    ]
    return run_supervised_worker(
        command,
        cwd=REPOSITORY_ROOT.resolve(strict=True),
        env=supervised_worker_environment(os.environ),
        limits=DYNAMIC_SUPERVISION_LIMITS,
        stage_limits=DYNAMIC_STAGE_LIMITS,
        progress=_progress,
        stdout_sink=sys.stdout,
        stderr_sink=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    forwarded = list(sys.argv[1:] if argv is None else argv)
    args = _arguments(forwarded)
    if not args.exchange_root:
        print("--exchange-root or ASP_MODEL_EXCHANGE_ROOT is required.", file=sys.stderr)
        return 2
    if not args.database:
        print("--database or ATLAS_SQLITE_PATH is required.", file=sys.stderr)
        return 2
    if args.bootstrap_resamples != 500 or args.bootstrap_seed != 20_260_817:
        print("The governed run requires bootstrap-resamples=500 and seed=20260817.", file=sys.stderr)
        return 2
    worker_environment = is_supervised_worker()
    if args.supervised_worker is not worker_environment:
        print(
            "The hidden worker argument and supervised-worker environment must match.",
            file=sys.stderr,
        )
        return 2
    if not worker_environment:
        try:
            result = _supervise(forwarded)
        except SupervisionError as exc:
            print(
                f"FAILED SUPERVISION {exc.reason}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return 1
        return result.returncode
    with WorkerEventEmitter(
        stage_names=tuple(DYNAMIC_STAGE_LIMITS),
        heartbeat_seconds=30.0,
    ) as emitter:
        status = _worker_main(args, progress=emitter.progress)
        emitter.finish(status)
        return status


if __name__ == "__main__":
    raise SystemExit(main())
