"""A tiny worker for the Phase 7D.4 Gate 14 TRUE-interprocess concurrency battery.

Runnable as ``python -m tests._interprocess_worker <command> <args...>`` in a SEPARATE OS process. It resolves
its runtime roots from ``ASP_MODEL_STUDIO_RUNTIME_ROOT`` (the env seam), so multiple worker processes contend on
the SAME isolated temp roots as the parent. Each command prints a single synchronizing token line and flushes.
"""
from __future__ import annotations

import os
import sys
import time


def _hold_until_release(release_path: str, max_seconds: float = 120.0) -> None:
    """Hold (keep the enclosing lock) DETERMINISTICALLY until the parent creates the RELEASE sentinel file. The sentinel
    — not any sleep duration — is the release signal; ``max_seconds`` is only a self-limiting safety fallback so a dead
    parent can never wedge the holder forever."""
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        if os.path.exists(release_path):
            return
        time.sleep(0.01)


def main() -> int:
    cmd = sys.argv[1]
    from server.sports_cockpit import gen3_authority as A
    from server.sports_cockpit.interprocess_lock import LockBusy, interprocess_lock

    if cmd == "trylock":
        try:
            with interprocess_lock(sys.argv[2], blocking=False):
                print("ACQUIRED", flush=True)
        except LockBusy:
            print("BUSY", flush=True)

    elif cmd == "holdlock":                              # acquire, signal ACQUIRED, hold until the RELEASE sentinel
        try:
            with interprocess_lock(sys.argv[2], blocking=False):
                print("ACQUIRED", flush=True)
                _hold_until_release(sys.argv[3])
        except LockBusy:
            print("BUSY", flush=True)

    elif cmd == "holdexec":                              # hold the per-project heavy-work exec lock until RELEASE
        proj = sys.argv[2]
        try:
            with interprocess_lock(str(A._project_exec_lock_path(proj)), blocking=False):
                print("ACQUIRED", flush=True)
                _hold_until_release(sys.argv[3])
        except LockBusy:
            print("BUSY", flush=True)

    elif cmd == "migrate":                               # create-once canonical registry migration
        out = A.migrate_registry()
        print("MIGRATED " + out["migrationId"], flush=True)

    elif cmd == "evput":                                 # create-once evidence-registry mapping
        proj, run_id, sha = sys.argv[2], sys.argv[3], sys.argv[4]
        try:
            A._evidence_registry_put(proj, run_id, sha)
            print("OK", flush=True)
        except A.AuthorityError:
            print("CONFLICT", flush=True)

    elif cmd == "execute":                               # a full governed run through the single authorized path
        proj, research = sys.argv[2], sys.argv[3]
        try:
            b = A.create_binding(actor="w@asp", project_id=proj, dataset_version_id=research)
            au = A.issue_run_authority(actor="w@asp", project_id=proj, binding_id=b["bindingId"],
                                       model_family="governed_hgb", hyperparameters={"maxIter": 15})
            ev = A.execute(actor="w@asp", project_id=proj, run_authority_id=au["runAuthorityId"])
            print("RUN " + ev["experimentRunId"], flush=True)
        except A.BusyError:
            print("BUSY", flush=True)

    else:
        print("UNKNOWN", flush=True)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
