from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import timedelta
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.persistence.db import Database  # noqa: E402
from server.sports_datasets.access import approved_package_root  # noqa: E402
from server.sports_datasets.constants import PROJECT_ID  # noqa: E402
from server.sports_datasets.consumer import (  # noqa: E402
    SportsDatasetManifestConsumer,
    raw_absolute_path,
    reject_reparse_chain,
)
from server.sports_identity_bridges.consumer import (  # noqa: E402
    SportsIdentityBridgeV1Consumer,
    approved_bridge_root,
)
from server.sports_phase4.participation_runner import (  # noqa: E402
    dynamic_state_source_from_run,
    estimate_participation_runtime,
    run_mlb_participation_usage,
)
from server.sports_phase4.registry import (  # noqa: E402
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


MILESTONE = "Phase 4 Milestone B"
DATASET_VALIDATION_CACHE_RELATIVE = Path("dataset-validation") / "validation-cache.json"
SUPERVISED_WORKER_ARGUMENT = "--supervised-worker"
PARTICIPATION_STAGE_LIMITS: dict[str, float] = {
    "TRAINING_LINEUP_COMPONENT": 90.0 * 60.0,
    "TRAINING_STARTER_DURATION_COMPONENT": 90.0 * 60.0,
    "TRAINING_BULLPEN_USAGE_COMPONENT": 120.0 * 60.0,
}
PARTICIPATION_SUPERVISION_LIMITS = SupervisionLimits(
    overall_seconds=8.0 * 60.0 * 60.0,
    silence_seconds=90.0,
    rss_bytes=8 * 1024**3,
)
_STARTED = time.monotonic()


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


def _progress(stage: str, evidence: Mapping[str, Any]) -> None:
    nested = evidence.get("evidence")
    values = dict(nested) if isinstance(nested, Mapping) else dict(evidence)
    if "elapsedSeconds" in evidence:
        values["elapsedSeconds"] = evidence["elapsedSeconds"]
    if evidence.get("activeStage") is not None:
        values.setdefault("activeStage", evidence["activeStage"])
    elapsed = float(values.get("elapsedSeconds", time.monotonic() - _STARTED) or 0.0)
    processed = int(
        values.get(
            "rowsProcessed",
            values.get("referencesProcessed", values.get("partitionsProcessed", 0)),
        )
        or 0
    )
    total = int(
        values.get(
            "rowsTotal",
            values.get("referencesTotal", values.get("partitionsTotal", 0)),
        )
        or 0
    )
    throughput = (
        f"{processed / elapsed:,.0f} rows/sec"
        if processed > 0 and elapsed > 0
        else "unavailable"
    )
    eta = (
        _duration(float(values["etaSeconds"]))
        if values.get("etaSeconds") is not None
        else "unavailable"
    )
    print(
        "\n".join(
            [
                "ASP MODEL STUDIO — MLB PARTICIPATION & USAGE RESEARCH",
                f"Milestone: {MILESTONE}",
                "Current component: "
                f"{values.get('currentComponent', values.get('componentType', values.get('activeStage', 'multi-component')))}",
                f"Stage: {stage}",
                f"Elapsed: {_duration(elapsed)}",
                "Seasons/fold: "
                f"{values.get('validationSeason', values.get('currentSeason', values.get('foldId', 'not applicable')))}",
                "Partitions: "
                f"{values.get('partitionsProcessed', 0)} / {values.get('partitionsTotal', 'unavailable')}",
                f"Rows: {processed:,} / {total if total else 'unavailable'}",
                f"Candidate: {values.get('candidate', values.get('candidateId', 'not applicable'))}",
                f"Throughput: {throughput}",
                f"ETA: {eta}",
                f"Memory: {_memory()}",
                f"Errors: {values.get('errors', 0)}",
                "",
            ]
        ),
        flush=True,
    )


def _package_progress(
    callback: Callable[[str, Mapping[str, Any]], None],
    evidence: Mapping[str, Any],
) -> None:
    callback(str(evidence.get("stage", "AUTHORITY_VALIDATION")), evidence)


def _with_heartbeat(
    stage: str,
    callback: Callable[[], Any],
    *,
    progress: Callable[[str, Mapping[str, Any]], None],
) -> Any:
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="participation-cli") as executor:
        future = executor.submit(callback)
        while True:
            try:
                return future.result(timeout=30.0)
            except FutureTimeoutError:
                progress(
                    stage,
                    {
                        "currentComponent": "DYNAMIC_STATE_INPUT",
                        "elapsedSeconds": time.monotonic() - started,
                        "errors": 0,
                        "etaSeconds": None,
                    },
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
        if len(revision) != 40 or any(value not in "0123456789abcdef" for value in revision):
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
        untracked = sorted(value for value in untracked_output.split(b"\0") if value)
        if not tracked and not untracked:
            return f"git:{revision}"
        digest = hashlib.sha256()
        digest.update(b"ASP_MODEL_STUDIO_PARTICIPATION_WORKTREE_V1\0")
        digest.update(revision.encode("ascii"))
        digest.update(len(tracked).to_bytes(8, "big"))
        digest.update(tracked)
        for encoded_path in untracked:
            relative = Path(os.fsdecode(encoded_path))
            physical = raw_absolute_path(REPOSITORY_ROOT / relative)
            physical.relative_to(REPOSITORY_ROOT)
            reject_reparse_chain(physical, label="Participation revision input chain")
            metadata = physical.lstat()
            digest.update(len(encoded_path).to_bytes(4, "big"))
            digest.update(encoded_path)
            digest.update(stat.S_IFMT(metadata.st_mode).to_bytes(4, "big"))
            if stat.S_ISLNK(metadata.st_mode):
                content = os.readlink(physical).encode("utf-8")
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                content = physical.read_bytes()
            else:
                raise RuntimeError(
                    "untracked revision input must be a single-link regular file"
                )
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return f"git:{revision}+worktree-sha256:{digest.hexdigest()}"
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "Unable to derive content-bound source provenance; set "
            "ASP_MODEL_STUDIO_CODE_REVISION explicitly"
        ) from exc


def _validate_database(path: Path) -> None:
    reject_reparse_chain(path, label="Configured ASP Model Studio database chain")
    if not path.exists():
        raise RuntimeError("the initialized ASP Model Studio database is required")
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RuntimeError("database must be a single-link regular file")


def _validate_runtime_roots(dynamic_root: Path, output_root: Path) -> None:
    approved_dynamic = raw_absolute_path(
        REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
    )
    approved_output = raw_absolute_path(
        REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-phase4"
    )
    dynamic = raw_absolute_path(dynamic_root)
    output = raw_absolute_path(output_root)
    if dynamic != approved_dynamic or output != approved_output:
        raise RuntimeError("dynamic input and participation output roots differ")
    if dynamic == output:
        raise RuntimeError("dynamic input and participation output roots may not alias")
    for label, value, approved in (
        ("dynamic runtime", dynamic, approved_dynamic),
        ("participation runtime", output, approved_output),
    ):
        reject_reparse_chain(value, label=f"Configured {label} chain")
        if value.resolve(strict=False) != approved.resolve(strict=False):
            raise RuntimeError(f"{label} resolves outside its approved boundary")


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Phase 4 Milestone B lineup, conditional starter-duration, and "
            "bullpen-usage research from exact registered authorities."
        )
    )
    parser.add_argument("--exchange-root", default=os.getenv("ASP_MODEL_EXCHANGE_ROOT", ""))
    parser.add_argument("--database", default=os.getenv("ATLAS_SQLITE_PATH", ""))
    parser.add_argument(
        "--dynamic-runtime-root",
        default=os.getenv("ASP_MODEL_STUDIO_SPORTS_MODELING_ROOT", ""),
    )
    parser.add_argument(
        "--runtime-root",
        default=os.getenv("ASP_MODEL_STUDIO_PHASE4_RUNTIME_ROOT", ""),
    )
    parser.add_argument("--bootstrap-resamples", type=int, default=500)
    parser.add_argument("--user-id", default="target-local-administrator")
    parser.add_argument("--enable-optional-hgb", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument(SUPERVISED_WORKER_ARGUMENT, action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _dynamic_run_from_active(active: Mapping[str, Any]) -> dict[str, Any]:
    components = active.get("components")
    artifacts = active.get("artifacts")
    if not isinstance(components, Mapping) or not isinstance(artifacts, list):
        raise RuntimeError("active Phase 4 study is incomplete")
    dynamic = components.get("dynamicState")
    if not isinstance(dynamic, Mapping):
        raise RuntimeError("active Phase 4 dynamic-state component is required")
    artifact_ids = dynamic.get("artifactIds")
    if not isinstance(artifact_ids, list):
        raise RuntimeError("active dynamic-state artifact inventory differs")
    expected = set(artifact_ids)
    selected = [item for item in artifacts if isinstance(item, Mapping) and item.get("artifactId") in expected]
    if {item["artifactId"] for item in selected} != expected:
        raise RuntimeError("active dynamic-state artifact references are incomplete")
    return {"component": dict(dynamic), "artifacts": [dict(item) for item in selected]}


def _artifact_union(
    active_artifacts: list[Mapping[str, Any]],
    new_artifacts: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    union: dict[str, dict[str, Any]] = {}
    for item in [*active_artifacts, *new_artifacts]:
        if not isinstance(item, Mapping) or not isinstance(item.get("artifactId"), str):
            raise RuntimeError("Phase 4 artifact reference differs")
        normalized = dict(item)
        artifact_id = normalized["artifactId"]
        if artifact_id in union and union[artifact_id] != normalized:
            raise RuntimeError("duplicate Phase 4 artifact reference contradicts active evidence")
        union[artifact_id] = normalized
    return [union[key] for key in sorted(union)]


def _worker_main(
    args: argparse.Namespace,
    *,
    progress: Callable[[str, Mapping[str, Any]], None],
) -> int:
    approved_database = raw_absolute_path(
        REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "persistence" / "asp_model_studio.db"
    )
    requested_database = raw_absolute_path(Path(args.database))
    approved_dynamic_runtime = raw_absolute_path(
        REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-modeling"
    )
    requested_dynamic_runtime = raw_absolute_path(
        Path(args.dynamic_runtime_root)
        if args.dynamic_runtime_root
        else approved_dynamic_runtime
    )
    approved_runtime = raw_absolute_path(
        REPOSITORY_ROOT / ".runtime" / "asp-model-studio" / "sports-phase4"
    )
    requested_runtime = raw_absolute_path(
        Path(args.runtime_root) if args.runtime_root else approved_runtime
    )
    if requested_database != approved_database:
        print("--database must be the isolated ASP Model Studio database.", file=sys.stderr)
        return 2
    if requested_dynamic_runtime != approved_dynamic_runtime:
        print("--dynamic-runtime-root must be the governed sports-modeling root.", file=sys.stderr)
        return 2
    if requested_runtime != approved_runtime:
        print("--runtime-root must be the governed sports-phase4 root.", file=sys.stderr)
        return 2
    try:
        _validate_database(requested_database)
        _validate_runtime_roots(requested_dynamic_runtime, requested_runtime)
        database = Database(requested_database)
        database.initialize()
        _validate_database(requested_database)
        registry = SportsPhase4Registry(database)
        registry.validate_registered_authorities()
        active_envelope = registry.public_active()
        if not isinstance(active_envelope, Mapping) or not isinstance(
            active_envelope.get("phase4"), Mapping
        ):
            raise RuntimeError("an active Milestone A Phase 4 study is required")
        active = active_envelope["phase4"]
        dynamic_run = _dynamic_run_from_active(active)
        dynamic_source = _with_heartbeat(
            "VALIDATING_DYNAMIC_HISTORY_INDEX",
            lambda: dynamic_state_source_from_run(
                dynamic_run,
                runtime_root=requested_dynamic_runtime,
            ),
            progress=progress,
        )
        exchange_root = Path(args.exchange_root)
        validation_cache = raw_absolute_path(
            requested_dynamic_runtime / DATASET_VALIDATION_CACHE_RELATIVE
        )
        expected_validation_cache = raw_absolute_path(
            approved_dynamic_runtime / DATASET_VALIDATION_CACHE_RELATIVE
        )
        if validation_cache != expected_validation_cache:
            raise RuntimeError("dataset validation cache path differs from Milestone A")
        reject_reparse_chain(validation_cache, label="Milestone A dataset validation cache chain")
        if not validation_cache.is_file():
            raise RuntimeError("the warmed Milestone A dataset validation cache is required")
        cache_metadata = validation_cache.lstat()
        if not stat.S_ISREG(cache_metadata.st_mode) or cache_metadata.st_nlink != 1:
            raise RuntimeError("Milestone A dataset validation cache must be a single-link file")
        parent = SportsDatasetManifestConsumer(
            approved_package_root(exchange_root),
            cache_path=validation_cache,
            progress=lambda evidence: _package_progress(progress, evidence),
        ).validate()
        if parent.cache_misses != 0 or parent.cache_hits != len(parent.partitions):
            raise RuntimeError("Milestone B requires an exact fully warmed dataset-validation cache")
        bridge = SportsIdentityBridgeV1Consumer(
            approved_bridge_root(exchange_root),
            progress=lambda evidence: _package_progress(progress, evidence),
        ).validate()
        if args.preflight_only:
            progress(
                "PREFLIGHT_COMPLETE",
                {
                    "currentComponent": "MULTI_COMPONENT",
                    "elapsedSeconds": time.monotonic() - _STARTED,
                    "errors": 0,
                    "etaSeconds": None,
                },
            )
            return 0
        code_revision = _revision()
        result = run_mlb_participation_usage(
            project_id=PROJECT_ID,
            parent=parent,
            identity_bridge=bridge,
            dynamic_state=dynamic_source,
            runtime_root=requested_runtime,
            code_revision=code_revision,
            enable_optional_hgb=args.enable_optional_hgb,
            bootstrap_resamples=args.bootstrap_resamples,
            progress=progress,
        )
        by_type = {component["componentType"]: component for component in result["components"]}
        if set(by_type) != {"LINEUP_PROJECTION", "STARTER_DURATION", "BULLPEN_USAGE"}:
            raise RuntimeError("participation result component set differs")
        all_artifacts = _artifact_union(active["artifacts"], result["artifacts"])
        study = build_phase4_study_payload(
            phase3_baseline=active["phase3Baseline"],
            dynamic_state=active["components"]["dynamicState"],
            lineup=by_type["LINEUP_PROJECTION"],
            starter_duration=by_type["STARTER_DURATION"],
            bullpen_usage=by_type["BULLPEN_USAGE"],
            artifacts=all_artifacts,
            created_at=result["createdAt"],
            code_revision=result["codeRevision"],
            dataset=active["dataset"],
            identity_bridge=active["identityBridge"],
        )
        saved = registry.register(study, user_id=args.user_id)
        decisions = {
            component["componentType"]: component["decision"]["decision"]
            for component in result["components"]
        }
        print(
            "COMPLETED "
            f"run_id={result['runId']} "
            f"decisions={json.dumps(decisions, sort_keys=True, separators=(',', ':'))} "
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
        str(Path(__file__).resolve()),
        *argv,
        SUPERVISED_WORKER_ARGUMENT,
    ]
    return run_supervised_worker(
        command,
        cwd=REPOSITORY_ROOT.resolve(strict=True),
        env=supervised_worker_environment(os.environ),
        limits=PARTICIPATION_SUPERVISION_LIMITS,
        stage_limits=PARTICIPATION_STAGE_LIMITS,
        progress=_progress,
        stdout_sink=sys.stdout,
        stderr_sink=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    from scripts._retired_2025_guard import retire_2025  # Phase 7D.4 Gate 12 (B8)
    retire_2025()   # trains/scores 2025 participation + surfaces final2025 -> exit before any data open
    forwarded = list(sys.argv[1:] if argv is None else argv)
    args = _arguments(forwarded)
    if args.estimate_only:
        if args.supervised_worker or is_supervised_worker():
            print("Estimate-only mode may not impersonate a supervised worker.", file=sys.stderr)
            return 2
        print(
            json.dumps(
                estimate_participation_runtime(
                    enable_optional_hgb=args.enable_optional_hgb
                ),
                sort_keys=True,
            )
        )
        return 0
    if not args.exchange_root:
        print("--exchange-root or ASP_MODEL_EXCHANGE_ROOT is required.", file=sys.stderr)
        return 2
    if not args.database:
        print("--database or ATLAS_SQLITE_PATH is required.", file=sys.stderr)
        return 2
    if args.bootstrap_resamples != 500:
        print("The governed live run requires exactly 500 bootstrap resamples.", file=sys.stderr)
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
        stage_names=tuple(PARTICIPATION_STAGE_LIMITS),
        heartbeat_seconds=30.0,
    ) as emitter:
        status = _worker_main(args, progress=emitter.progress)
        emitter.finish(status)
        return status


if __name__ == "__main__":
    raise SystemExit(main())
