"""Bounded, Windows-compatible interprocess lock (Phase 7D.1 Gate 2 / Gate 23).

A trusted-local execution/migration guard that is safe ACROSS PROCESSES, not merely across threads of one
interpreter. It is implemented as an exclusive-create lockfile (``os.O_CREAT | os.O_EXCL``) carrying the
owner PID + a random token + a creation timestamp, with:

  - bounded acquisition timeout (never an unbounded queue);
  - safe stale-lock reclamation (dead owner PID, or age beyond ``stale_after``);
  - guaranteed release in a ``finally`` (context manager);
  - SAME-THREAD REENTRANCY so an in-process orchestrator (e.g. a feature-family ablation that runs a control
    then a challenger through the single authorized ``execute`` path) does not self-deadlock, while a
    concurrent request from another thread OR another process is still excluded (the file lock serializes
    even within one interpreter, so a second thread cannot create the same lockfile).

Pure stdlib; no third-party dependency. The caller supplies an already-contained lockfile path.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LockBusy(RuntimeError):
    """A non-blocking acquire found the lock held by another thread/process."""


class LockTimeout(RuntimeError):
    """A blocking acquire exceeded its bounded timeout."""


def _pid_alive(pid: int) -> bool:
    """Best-effort liveness of ``pid``. On an unknown/undeterminable state, returns True (conservative — a
    lock is only reclaimed on a POSITIVE dead-PID signal or on age), so a live long run is never stolen."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False  # no such process
            try:
                code = ctypes.c_ulong()
                ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                return bool(ok) and code.value == STILL_ACTIVE
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return True  # cannot determine → treat as alive (rely on age-based reclamation only)


class _FileLock:
    """One exclusive-create lockfile. Not reentrant on its own — reentrancy is layered above."""

    def __init__(self, path: Path, *, timeout: float, stale_after: float, poll: float = 0.05):
        self.path = Path(path)
        self.timeout = float(timeout)
        self.stale_after = float(stale_after)
        self.poll = float(poll)
        self.token = uuid.uuid4().hex
        self._held = False

    def _try_create(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        except PermissionError:
            return False  # Windows: O_EXCL create raced with a concurrent delete/create; treat as contended
        try:
            os.write(fd, json.dumps({"pid": os.getpid(), "token": self.token,
                                     "createdAt": time.time()}).encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        self._held = True
        return True

    def _reclaim_if_stale(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
            meta = json.loads(raw) if raw.strip() else {}
        except FileNotFoundError:
            return
        except Exception:
            meta = {}
        try:
            age = time.time() - float(meta.get("createdAt", 0.0))
        except Exception:
            age = float("inf")
        owner = meta.get("pid")
        stale = age >= self.stale_after or (isinstance(owner, int) and not _pid_alive(owner))
        if stale:
            try:
                os.replace(str(self.path), str(self.path) + f".stale-{uuid.uuid4().hex}")
            except FileNotFoundError:
                pass
            except Exception:
                pass
            else:
                # remove the moved-aside stale lock best-effort
                for p in self.path.parent.glob(self.path.name + ".stale-*"):
                    try:
                        p.unlink()
                    except Exception:
                        pass

    def acquire(self, *, blocking: bool) -> bool:
        if self._try_create():
            return True
        if not blocking:
            self._reclaim_if_stale()
            return self._try_create()  # one reclaim attempt for non-blocking callers
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            self._reclaim_if_stale()
            if self._try_create():
                return True
            time.sleep(self.poll)
        raise LockTimeout(f"could not acquire {self.path.name} within {self.timeout}s")

    def release(self) -> None:
        if not self._held:
            return
        try:
            raw = self.path.read_text(encoding="utf-8")
            meta = json.loads(raw) if raw.strip() else {}
        except Exception:
            meta = {}
        # only remove the lockfile if we still own it (token match) — never delete a reclaimer's lock
        if meta.get("token") == self.token:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self._held = False


# --------------------------------------------------------------------------- reentrant, cross-process API
# A per-key in-process RLock serializes THREADS of this interpreter first (same-thread reentrant), so only one
# thread at a time touches the cross-process lockfile — this eliminates the Windows create/unlink/resolve race
# under high intra-process contention while the file lock still enforces cross-PROCESS mutual exclusion.
_KEY_GUARD = threading.Lock()
_KEY_STATE: dict[str, dict] = {}  # lock path -> {"rlock": RLock, "filelock": _FileLock|None, "depth": int}


def _key_state(key: str) -> dict:
    with _KEY_GUARD:
        st = _KEY_STATE.get(key)
        if st is None:
            st = {"rlock": threading.RLock(), "filelock": None, "depth": 0}
            _KEY_STATE[key] = st
        return st


@contextmanager
def interprocess_lock(lock_path: Path | str, *, blocking: bool = True, timeout: float = 30.0,
                      stale_after: float = 1800.0) -> Iterator[None]:
    """Acquire an interprocess lock at ``lock_path``. Same-thread reentrant; a different thread of this process
    OR a different process is excluded. ``blocking=False`` raises :class:`LockBusy` instead of waiting. Always
    released in ``finally``."""
    key = str(Path(lock_path))
    st = _key_state(key)
    rlock = st["rlock"]
    got = rlock.acquire(blocking, timeout) if blocking else rlock.acquire(False)
    if not got:
        raise LockBusy(f"lock is held by another thread: {Path(lock_path).name}")
    try:
        if st["depth"] == 0:                      # first (non-reentrant) acquire in this thread -> take the file lock
            fl = _FileLock(Path(lock_path), timeout=timeout, stale_after=stale_after)
            try:
                ok = fl.acquire(blocking=blocking)
            except LockTimeout as exc:
                raise LockBusy(str(exc)) from exc
            if not ok:
                raise LockBusy(f"lock is held by another process: {Path(lock_path).name}")
            st["filelock"] = fl
        st["depth"] += 1
        try:
            yield
        finally:
            st["depth"] -= 1
            if st["depth"] == 0 and st["filelock"] is not None:
                fl = st["filelock"]; st["filelock"] = None
                fl.release()
    finally:
        rlock.release()
