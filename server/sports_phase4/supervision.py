from __future__ import annotations

import json
import math
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO


WORKER_ENVIRONMENT_FLAG = "ASP_PHASE4_SUPERVISED_WORKER"
WORKER_EVENT_PREFIX = "@@ASP_PHASE4_WORKER_EVENT@@"
WORKER_EVENT_SCHEMA_VERSION = "ASP_PHASE4_WORKER_EVENT_V1"
WORKER_EVENT_TYPES = frozenset({"START", "PROGRESS", "HEARTBEAT", "EXIT"})
_WORKER_EVENT_KEYS = {
    "schemaVersion",
    "event",
    "pid",
    "sequence",
    "stage",
    "activeStage",
    "operationId",
    "elapsedSeconds",
    "rssBytes",
    "evidence",
}


class SupervisionError(RuntimeError):
    """Fail-closed worker supervision error with preserved process evidence."""

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        result: SupervisedWorkerResult | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.result = result


@dataclass(frozen=True)
class SupervisionLimits:
    overall_seconds: float
    silence_seconds: float = 90.0
    rss_bytes: int = 8 * 1024**3
    poll_seconds: float = 0.25
    termination_grace_seconds: float = 2.0

    def __post_init__(self) -> None:
        for name in (
            "overall_seconds",
            "silence_seconds",
            "poll_seconds",
            "termination_grace_seconds",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0.0
            ):
                raise ValueError(f"{name} must be finite and positive")
        if (
            isinstance(self.rss_bytes, bool)
            or not isinstance(self.rss_bytes, int)
            or self.rss_bytes <= 0
        ):
            raise ValueError("rss_bytes must be a positive integer")


@dataclass(frozen=True)
class SupervisedWorkerResult:
    command: tuple[str, ...]
    returncode: int
    elapsed_seconds: float
    peak_tree_rss_bytes: int
    stdout: str
    stderr: str
    events: tuple[dict[str, Any], ...]


def supervised_worker_environment(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(os.environ if base is None else base)
    environment[WORKER_ENVIRONMENT_FLAG] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def is_supervised_worker(environment: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environment is None else environment
    return values.get(WORKER_ENVIRONMENT_FLAG) == "1"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    return str(value)


def _own_rss_bytes() -> int:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:
        return 0


class WorkerEventEmitter:
    """Thread-safe NDJSON worker protocol plus an independent heartbeat."""

    def __init__(
        self,
        *,
        stage_names: Sequence[str],
        heartbeat_seconds: float = 30.0,
        stream: TextIO | None = None,
    ) -> None:
        normalized = tuple(sorted(set(stage_names)))
        if not normalized or any(not isinstance(value, str) or not value for value in normalized):
            raise ValueError("stage_names must contain non-empty strings")
        if (
            isinstance(heartbeat_seconds, bool)
            or not isinstance(heartbeat_seconds, (int, float))
            or not 0.0 < float(heartbeat_seconds) <= 60.0
        ):
            raise ValueError("heartbeat_seconds must be in (0, 60]")
        self.stage_names = frozenset(normalized)
        self.heartbeat_seconds = float(heartbeat_seconds)
        self.stream = stream or sys.stdout
        self.started = time.monotonic()
        self.sequence = 0
        self.operation_sequence = 0
        self.current_stage: str | None = None
        self.current_operation_id: str | None = None
        self.current_evidence: dict[str, Any] = {}
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None
        self.finished = False

    def __enter__(self) -> WorkerEventEmitter:
        self._write("START", "WORKER_START", {})
        self.thread = threading.Thread(
            target=self._heartbeat,
            name="phase4-supervised-worker-heartbeat",
            daemon=True,
        )
        self.thread.start()
        return self

    def _new_operation(self, stage: str) -> None:
        self.operation_sequence += 1
        self.current_stage = stage
        self.current_operation_id = f"{stage}:{self.operation_sequence}"

    def progress(self, stage: str, evidence: Mapping[str, Any]) -> None:
        if not isinstance(stage, str) or not stage:
            raise ValueError("worker progress stage must be non-empty")
        if not isinstance(evidence, Mapping):
            raise TypeError("worker progress evidence must be a mapping")
        with self.lock:
            values = dict(evidence)
            nested_stage = values.get("blockingStage", values.get("modelStage"))
            if stage in self.stage_names and nested_stage is None:
                self._new_operation(stage)
            elif nested_stage in self.stage_names:
                if self.current_stage != nested_stage or self.current_operation_id is None:
                    self._new_operation(str(nested_stage))
            self.current_evidence = _json_safe(values)
            if stage.endswith("_FIT_FINISHED") and nested_stage == self.current_stage:
                self.current_stage = None
                self.current_operation_id = None
            self._write("PROGRESS", stage, values)

    def _heartbeat(self) -> None:
        while not self.stopped.wait(self.heartbeat_seconds):
            self._write("HEARTBEAT", "WORKER_HEARTBEAT", self.current_evidence)

    def finish(self, returncode: int) -> None:
        if isinstance(returncode, bool) or not isinstance(returncode, int):
            raise TypeError("worker returncode must be an integer")
        with self.lock:
            if self.finished:
                return
            # Claim finalization while holding the same lock used for protocol
            # writes so concurrent callers cannot emit duplicate EXIT records.
            self.finished = True
            self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=min(self.heartbeat_seconds, 1.0))
        with self.lock:
            self.current_stage = None
            self.current_operation_id = None
            self._write("EXIT", "WORKER_EXIT", {"returnCode": returncode})

    def _write(self, event: str, stage: str, evidence: Mapping[str, Any]) -> None:
        with self.lock:
            self.sequence += 1
            payload = {
                "schemaVersion": WORKER_EVENT_SCHEMA_VERSION,
                "event": event,
                "pid": os.getpid(),
                "sequence": self.sequence,
                "stage": stage,
                "activeStage": self.current_stage,
                "operationId": self.current_operation_id,
                "elapsedSeconds": round(time.monotonic() - self.started, 6),
                "rssBytes": _own_rss_bytes(),
                "evidence": _json_safe(evidence),
            }
            encoded = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            self.stream.write(f"{WORKER_EVENT_PREFIX}{encoded}\n")
            self.stream.flush()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.finish(0 if exc_type is None else 1)


class _WindowsJob:
    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        )
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        information = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        information.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise OSError(error, "SetInformationJobObject failed")
        self.ctypes = ctypes
        self.kernel32 = kernel32
        self.psapi = psapi
        self.wintypes = wintypes
        self.process_memory_counters_type = PROCESS_MEMORY_COUNTERS_EX
        self.extended_limit_information_type = JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        self.handle = handle

    def assign(self, process: subprocess.Popen[str]) -> None:
        process_handle = self.ctypes.c_void_p(int(process._handle))  # type: ignore[attr-defined]
        if not self.kernel32.AssignProcessToJobObject(self.handle, process_handle):
            raise OSError(self.ctypes.get_last_error(), "AssignProcessToJobObject failed")

    def terminate(self) -> None:
        if self.handle:
            self.kernel32.TerminateJobObject(self.handle, 1)

    def pids(self) -> tuple[int, ...]:
        capacity = 64
        while True:
            size = 8 + capacity * self.ctypes.sizeof(self.ctypes.c_size_t)
            buffer = self.ctypes.create_string_buffer(size)
            returned = self.wintypes.DWORD()
            if not self.kernel32.QueryInformationJobObject(
                self.handle,
                3,  # JobObjectBasicProcessIdList
                buffer,
                size,
                self.ctypes.byref(returned),
            ):
                error = self.ctypes.get_last_error()
                if error == 122:  # ERROR_INSUFFICIENT_BUFFER
                    capacity *= 2
                    continue
                raise OSError(error, "QueryInformationJobObject failed")
            header = self.ctypes.cast(
                buffer,
                self.ctypes.POINTER(self.wintypes.DWORD * 2),
            ).contents
            assigned = int(header[0])
            listed = int(header[1])
            if assigned > capacity:
                capacity = max(capacity * 2, assigned)
                continue
            pids = self.ctypes.cast(
                self.ctypes.byref(buffer, 8),
                self.ctypes.POINTER(self.ctypes.c_size_t * listed),
            ).contents
            return tuple(int(raw_pid) for raw_pid in pids)

    def rss_bytes(self) -> int:
        # PeakJobMemoryUsed is maintained by the kernel for the complete job,
        # including descendants.  It remains available across short-lived PID
        # races and is deliberately conservative for the hard memory ceiling.
        information = self.extended_limit_information_type()
        returned = self.wintypes.DWORD()
        if not self.kernel32.QueryInformationJobObject(
            self.handle,
            9,  # JobObjectExtendedLimitInformation
            self.ctypes.byref(information),
            self.ctypes.sizeof(information),
            self.ctypes.byref(returned),
        ):
            raise OSError(
                self.ctypes.get_last_error(),
                "QueryInformationJobObject memory accounting failed",
            )
        peak_job_memory = int(information.PeakJobMemoryUsed)

        total = 0
        for raw_pid in self.pids():
            process_handle = self.kernel32.OpenProcess(
                0x1000 | 0x0010,  # QUERY_LIMITED_INFORMATION | VM_READ
                False,
                int(raw_pid),
            )
            if not process_handle:
                # Kernel job accounting above still covers this PID.  Never
                # silently substitute a partial per-process total.
                return peak_job_memory
            try:
                counters = self.process_memory_counters_type()
                counters.cb = self.ctypes.sizeof(counters)
                if not self.psapi.GetProcessMemoryInfo(
                    process_handle,
                    self.ctypes.byref(counters),
                    counters.cb,
                ):
                    return peak_job_memory
                total += int(counters.WorkingSetSize)
            finally:
                self.kernel32.CloseHandle(process_handle)
        return max(total, peak_job_memory)

    def close(self) -> None:
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


def _terminate_process_tree(
    process: subprocess.Popen[str],
    *,
    job: _WindowsJob | None,
    grace_seconds: float,
) -> None:
    if job is not None:
        job.terminate()
    else:
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (OSError, ProcessLookupError):
            pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=grace_seconds)


def _tree_rss(process_id: int, *, job: _WindowsJob | None) -> int:
    if job is not None:
        return job.rss_bytes()
    proc = Path("/proc")
    if not proc.is_dir():
        raise OSError("process-tree RSS accounting is unavailable")
    pending = [process_id]
    observed: set[int] = set()
    total = 0
    page_size = os.sysconf("SC_PAGE_SIZE")
    while pending:
        pid = pending.pop()
        if pid in observed:
            continue
        observed.add(pid)
        try:
            statm = (proc / str(pid) / "statm").read_text(encoding="ascii").split()
            total += int(statm[1]) * page_size
            children = (
                proc / str(pid) / "task" / str(pid) / "children"
            ).read_text(encoding="ascii").split()
            pending.extend(int(value) for value in children)
        except (FileNotFoundError, ProcessLookupError):
            continue
    return total


def _tree_pids(process_id: int, *, job: _WindowsJob | None) -> set[int]:
    if job is not None:
        return set(job.pids())
    proc = Path("/proc")
    if not proc.is_dir():
        return {process_id}
    pending = [process_id]
    observed: set[int] = set()
    while pending:
        pid = pending.pop()
        if pid in observed:
            continue
        observed.add(pid)
        try:
            children = (
                proc / str(pid) / "task" / str(pid) / "children"
            ).read_text(encoding="ascii").split()
            pending.extend(int(value) for value in children)
        except (FileNotFoundError, ProcessLookupError):
            continue
    return observed


def _validated_event(
    line: str,
    *,
    allowed_pids: set[int],
    protocol_pid: int | None,
    previous_sequence: int,
) -> dict[str, Any]:
    try:
        value = json.loads(line[len(WORKER_EVENT_PREFIX) :])
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SupervisionError("PROTOCOL_ERROR", "worker emitted malformed protocol JSON") from exc
    if not isinstance(value, dict) or set(value) != _WORKER_EVENT_KEYS:
        raise SupervisionError("PROTOCOL_ERROR", "worker event fields differ")
    if (
        value.get("schemaVersion") != WORKER_EVENT_SCHEMA_VERSION
        or value.get("event") not in WORKER_EVENT_TYPES
        or isinstance(value.get("pid"), bool)
        or not isinstance(value.get("pid"), int)
        or (
            value.get("pid") != protocol_pid
            if protocol_pid is not None
            else value.get("pid") not in allowed_pids
        )
        or isinstance(value.get("sequence"), bool)
        or not isinstance(value.get("sequence"), int)
        or value["sequence"] != previous_sequence + 1
        or not isinstance(value.get("stage"), str)
        or not value["stage"]
        or value.get("activeStage") is not None
        and (not isinstance(value["activeStage"], str) or not value["activeStage"])
        or value.get("operationId") is not None
        and (not isinstance(value["operationId"], str) or not value["operationId"])
        or isinstance(value.get("elapsedSeconds"), bool)
        or not isinstance(value.get("elapsedSeconds"), (int, float))
        or not math.isfinite(float(value["elapsedSeconds"]))
        or float(value["elapsedSeconds"]) < 0.0
        or isinstance(value.get("rssBytes"), bool)
        or not isinstance(value.get("rssBytes"), int)
        or value["rssBytes"] < 0
        or not isinstance(value.get("evidence"), dict)
    ):
        raise SupervisionError("PROTOCOL_ERROR", "worker event value differs")
    if (value["activeStage"] is None) != (value["operationId"] is None):
        raise SupervisionError("PROTOCOL_ERROR", "worker operation binding differs")
    return value


def run_supervised_worker(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    limits: SupervisionLimits,
    stage_limits: Mapping[str, float],
    progress: Callable[[str, Mapping[str, Any]], None] | None = None,
    stdout_sink: TextIO | None = None,
    stderr_sink: TextIO | None = None,
) -> SupervisedWorkerResult:
    """Run one whole CLI worker behind hard time, silence, RSS, and tree-kill gates."""

    normalized_command = tuple(command)
    if not normalized_command or any(not isinstance(value, str) or not value for value in normalized_command):
        raise ValueError("command must contain non-empty strings")
    if not isinstance(cwd, Path) or not cwd.is_absolute():
        raise ValueError("cwd must be an absolute Path")
    if env.get(WORKER_ENVIRONMENT_FLAG) != "1":
        raise ValueError("worker environment is missing the supervision flag")
    normalized_stage_limits = dict(stage_limits)
    if not normalized_stage_limits or any(
        not isinstance(name, str)
        or not name
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
        for name, value in normalized_stage_limits.items()
    ):
        raise ValueError("stage_limits must map stage names to positive finite seconds")
    stdout_target = stdout_sink or sys.stdout
    stderr_target = stderr_sink or sys.stderr
    started = time.monotonic()
    job: _WindowsJob | None = None
    process: subprocess.Popen[str] | None = None
    output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    events: list[dict[str, Any]] = []
    peak_rss = 0
    violation: tuple[str, str] | None = None

    try:
        if os.name == "nt":
            job = _WindowsJob()
        popen_options: dict[str, Any] = {
            "cwd": str(cwd),
            "env": dict(env),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True
        try:
            process = subprocess.Popen(normalized_command, **popen_options)
            if job is not None:
                job.assign(process)
        except Exception as exc:
            if process is not None:
                _terminate_process_tree(
                    process,
                    job=job,
                    grace_seconds=limits.termination_grace_seconds,
                )
            raise SupervisionError("SPAWN_ERROR", f"unable to start supervised worker: {exc}") from exc

        def read_stream(name: str, stream: TextIO) -> None:
            try:
                for line in iter(stream.readline, ""):
                    output_queue.put((name, line))
            finally:
                output_queue.put((name, None))

        assert process.stdout is not None and process.stderr is not None
        readers = [
            threading.Thread(
                target=read_stream,
                args=("stdout", process.stdout),
                name="phase4-worker-stdout",
                daemon=True,
            ),
            threading.Thread(
                target=read_stream,
                args=("stderr", process.stderr),
                name="phase4-worker-stderr",
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()

        last_event_at = started
        previous_sequence = 0
        protocol_pid: int | None = None
        saw_start = False
        saw_exit = False
        exit_event_code: int | None = None
        active_operation: str | None = None
        active_stage: str | None = None
        operation_started = started
        closed_streams: set[str] = set()

        while True:
            try:
                name, line = output_queue.get(timeout=limits.poll_seconds)
                if line is None:
                    closed_streams.add(name)
                elif name == "stdout" and line.startswith(WORKER_EVENT_PREFIX):
                    try:
                        event = _validated_event(
                            line.rstrip("\r\n"),
                            allowed_pids=_tree_pids(process.pid, job=job),
                            protocol_pid=protocol_pid,
                            previous_sequence=previous_sequence,
                        )
                    except SupervisionError as exc:
                        violation = (exc.reason, str(exc))
                        break
                    previous_sequence = int(event["sequence"])
                    if protocol_pid is None:
                        protocol_pid = int(event["pid"])
                    if not saw_start:
                        if event["event"] != "START":
                            violation = ("PROTOCOL_ERROR", "worker START event is missing")
                            break
                        saw_start = True
                    elif event["event"] == "START":
                        violation = ("PROTOCOL_ERROR", "worker emitted duplicate START")
                        break
                    if event["event"] == "EXIT":
                        if saw_exit or set(event["evidence"]) != {"returnCode"}:
                            violation = ("PROTOCOL_ERROR", "worker EXIT event differs")
                            break
                        exit_event_code = event["evidence"]["returnCode"]
                        if isinstance(exit_event_code, bool) or not isinstance(exit_event_code, int):
                            violation = ("PROTOCOL_ERROR", "worker EXIT code differs")
                            break
                        saw_exit = True
                    elif saw_exit:
                        violation = ("PROTOCOL_ERROR", "worker emitted evidence after EXIT")
                        break
                    events.append(event)
                    last_event_at = time.monotonic()
                    event_operation = event["operationId"]
                    event_stage = event["activeStage"]
                    if event_operation is None:
                        active_operation = None
                        active_stage = None
                    else:
                        if event_stage not in normalized_stage_limits:
                            violation = (
                                "PROTOCOL_ERROR",
                                "worker activated an ungoverned stage limit",
                            )
                            break
                        if event_operation != active_operation:
                            active_operation = str(event_operation)
                            active_stage = str(event_stage)
                            operation_started = last_event_at
                        elif event_stage != active_stage:
                            violation = (
                                "PROTOCOL_ERROR",
                                "worker operation changed its stage binding",
                            )
                            break
                    if progress is not None:
                        try:
                            callback_evidence = dict(event["evidence"])
                            # Protocol metadata is prefixed so it cannot
                            # overwrite identically named scientific evidence.
                            callback_evidence.update(
                                {
                                    "workerEvent": event["event"],
                                    "workerElapsedSeconds": event["elapsedSeconds"],
                                    "workerRssBytes": event["rssBytes"],
                                    "workerActiveStage": event["activeStage"],
                                    "workerOperationId": event["operationId"],
                                }
                            )
                            progress(str(event["stage"]), callback_evidence)
                        except Exception as exc:
                            violation = (
                                "PROTOCOL_ERROR",
                                f"supervisor progress callback failed: {exc}",
                            )
                            break
                elif name == "stdout":
                    stdout_parts.append(line)
                    stdout_target.write(line)
                    stdout_target.flush()
                else:
                    stderr_parts.append(line)
                    stderr_target.write(line)
                    stderr_target.flush()
            except queue.Empty:
                pass

            now = time.monotonic()
            elapsed = now - started
            try:
                rss = _tree_rss(process.pid, job=job)
            except OSError as exc:
                violation = (
                    "RSS_LIMIT",
                    f"worker tree RSS accounting failed closed: {exc}",
                )
                break
            peak_rss = max(peak_rss, rss)
            if rss > limits.rss_bytes:
                violation = (
                    "RSS_LIMIT",
                    f"worker tree RSS {rss} exceeded {limits.rss_bytes} bytes",
                )
                break
            if elapsed > limits.overall_seconds:
                violation = ("OVERALL_LIMIT", "worker exceeded the overall runtime limit")
                break
            if now - last_event_at > limits.silence_seconds:
                violation = ("SILENCE_LIMIT", "worker exceeded the progress-silence limit")
                break
            if active_operation is not None and active_stage is not None:
                if now - operation_started > float(normalized_stage_limits[active_stage]):
                    violation = (
                        "FIT_LIMIT",
                        f"worker operation {active_operation} exceeded its stage limit",
                    )
                    break
            returncode = process.poll()
            if returncode is not None and closed_streams == {"stdout", "stderr"} and output_queue.empty():
                break

        if violation is not None:
            _terminate_process_tree(
                process,
                job=job,
                grace_seconds=limits.termination_grace_seconds,
            )
        else:
            process.wait(timeout=limits.termination_grace_seconds)
        for reader in readers:
            reader.join(timeout=limits.termination_grace_seconds)
        while True:
            try:
                name, line = output_queue.get_nowait()
            except queue.Empty:
                break
            if line is None or line.startswith(WORKER_EVENT_PREFIX):
                continue
            if name == "stdout":
                stdout_parts.append(line)
                stdout_target.write(line)
                stdout_target.flush()
            else:
                stderr_parts.append(line)
                stderr_target.write(line)
                stderr_target.flush()
        result = SupervisedWorkerResult(
            command=normalized_command,
            returncode=int(process.returncode if process.returncode is not None else 1),
            elapsed_seconds=time.monotonic() - started,
            peak_tree_rss_bytes=peak_rss,
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            events=tuple(events),
        )
        if violation is not None:
            raise SupervisionError(violation[0], violation[1], result=result)
        if (
            not saw_start
            or not saw_exit
            or exit_event_code != result.returncode
            or not events
            or events[-1]["event"] != "EXIT"
        ):
            raise SupervisionError(
                "PROTOCOL_ERROR",
                "worker terminated without a matching START/EXIT protocol",
                result=result,
            )
        return result
    finally:
        if process is not None and process.poll() is None:
            _terminate_process_tree(
                process,
                job=job,
                grace_seconds=limits.termination_grace_seconds,
            )
        if process is not None:
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        if job is not None:
            job.close()


__all__ = [
    "SupervisedWorkerResult",
    "SupervisionError",
    "SupervisionLimits",
    "WORKER_ENVIRONMENT_FLAG",
    "WORKER_EVENT_PREFIX",
    "WORKER_EVENT_SCHEMA_VERSION",
    "WorkerEventEmitter",
    "is_supervised_worker",
    "run_supervised_worker",
    "supervised_worker_environment",
]
