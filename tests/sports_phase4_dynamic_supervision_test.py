from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from server.sports_phase4.supervision import (
    SupervisionError,
    SupervisionLimits,
    WORKER_EVENT_PREFIX,
    WorkerEventEmitter,
    run_supervised_worker,
    supervised_worker_environment,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _pid_exists(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def _worker_source(body: str, *, governed_stage: str = "FIT") -> str:
    return (
        "from server.sports_phase4.supervision import WorkerEventEmitter\n"
        "import os, subprocess, sys, time\n"
        f"with WorkerEventEmitter(stage_names=({governed_stage!r},), "
        "heartbeat_seconds=0.05) as emitter:\n"
        + "\n".join(f"    {line}" for line in body.splitlines())
        + "\n"
    )


def _run(
    body: str,
    *,
    overall: float = 15.0,
    silence: float = 1.0,
    rss_bytes: int = 1024**3,
    fit_seconds: float = 1.0,
    governed_stage: str = "FIT",
):
    stdout = io.StringIO()
    stderr = io.StringIO()
    return run_supervised_worker(
        (
            sys.executable,
            "-B",
            "-u",
            "-c",
            _worker_source(body, governed_stage=governed_stage),
        ),
        cwd=REPOSITORY_ROOT,
        env=supervised_worker_environment(os.environ),
        limits=SupervisionLimits(
            overall_seconds=overall,
            silence_seconds=silence,
            rss_bytes=rss_bytes,
            poll_seconds=0.02,
            termination_grace_seconds=0.5,
        ),
        stage_limits={governed_stage: fit_seconds},
        stdout_sink=stdout,
        stderr_sink=stderr,
    )


class SportsPhase4DynamicSupervisionTest(unittest.TestCase):
    def test_fit_finished_event_clears_operation_as_one_atomic_wire_state(self) -> None:
        stream = io.StringIO()
        stage = "TUNING_DYNAMIC_LOGISTIC_2023"
        with WorkerEventEmitter(
            stage_names=(stage,),
            heartbeat_seconds=30.0,
            stream=stream,
        ) as emitter:
            emitter.progress(stage, {"candidateId": "D1"})
            emitter.progress(
                "DYNAMIC_MODEL_FIT_FINISHED",
                {"blockingStage": stage, "candidateId": "D1"},
            )
        events = [
            json.loads(line[len(WORKER_EVENT_PREFIX) :])
            for line in stream.getvalue().splitlines()
        ]
        started = next(event for event in events if event["stage"] == stage)
        finished = next(
            event for event in events if event["stage"] == "DYNAMIC_MODEL_FIT_FINISHED"
        )
        self.assertEqual(started["activeStage"], stage)
        self.assertIsNotNone(started["operationId"])
        self.assertIsNone(finished["activeStage"])
        self.assertIsNone(finished["operationId"])

    def test_clean_worker_forwards_output_and_preserves_protocol_evidence(self) -> None:
        callbacks: list[tuple[str, dict[str, object]]] = []
        stdout = io.StringIO()
        stderr = io.StringIO()
        result = run_supervised_worker(
            (sys.executable, "-B", "-u", "-c", _worker_source(
                "emitter.progress('FIT', {'candidateId': 'fixture', "
                "'workerElapsedSeconds': 'scientific'})\n"
                "print('ordinary-output', flush=True)\n"
                "emitter.finish(0)"
            )),
            cwd=REPOSITORY_ROOT,
            env=supervised_worker_environment(os.environ),
            limits=SupervisionLimits(
                overall_seconds=15.0,
                silence_seconds=1.0,
                rss_bytes=1024**3,
                poll_seconds=0.02,
                termination_grace_seconds=0.5,
            ),
            stage_limits={"FIT": 1.0},
            progress=lambda stage, evidence: callbacks.append((stage, dict(evidence))),
            stdout_sink=stdout,
            stderr_sink=stderr,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "ordinary-output\n")
        self.assertEqual(result.events[0]["event"], "START")
        self.assertEqual(result.events[-1]["event"], "EXIT")
        self.assertGreater(result.peak_tree_rss_bytes, 0)
        progress_evidence = next(
            evidence for stage, evidence in callbacks if stage == "FIT"
        )
        self.assertEqual(progress_evidence["candidateId"], "fixture")
        self.assertIsInstance(progress_evidence["workerElapsedSeconds"], float)
        self.assertIn("workerRssBytes", progress_evidence)
        self.assertEqual(progress_evidence["workerActiveStage"], "FIT")
        self.assertTrue(str(progress_evidence["workerOperationId"]).startswith("FIT:"))

    def test_fit_limit_kills_worker_descendant_and_prevents_postfit_write(self) -> None:
        marker = REPOSITORY_ROOT / ".tmp" / f"supervision-marker-{uuid.uuid4().hex}"
        source = (
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            "print(f'CHILD_PID={child.pid}', flush=True)\n"
            "emitter.progress('FIT', {'candidateId': 'hung'})\n"
            "time.sleep(30)\n"
            f"open({str(marker)!r}, 'w', encoding='utf-8').write('registration')\n"
            "emitter.finish(0)"
        )
        with self.assertRaises(SupervisionError) as raised:
            _run(source, fit_seconds=0.2)
        self.assertEqual(raised.exception.reason, "FIT_LIMIT")
        result = raised.exception.result
        self.assertIsNotNone(result)
        match = re.search(r"CHILD_PID=(\d+)", result.stdout)
        self.assertIsNotNone(match)
        child_pid = int(match.group(1))
        deadline = time.monotonic() + 2.0
        while _pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(_pid_exists(child_pid))
        self.assertFalse(marker.exists())

    def test_dynamic_fit_start_activates_operation_and_is_hard_stopped(self) -> None:
        stage = "TUNING_DYNAMIC_LOGISTIC_2023"
        with self.assertRaises(SupervisionError) as raised:
            _run(
                f"emitter.progress({stage!r}, {{'candidateId': 'D1'}})\n"
                "time.sleep(30)",
                fit_seconds=0.2,
                governed_stage=stage,
            )
        self.assertEqual(raised.exception.reason, "FIT_LIMIT")
        result = raised.exception.result
        self.assertIsNotNone(result)
        activation = next(event for event in result.events if event["stage"] == stage)
        self.assertEqual(activation["activeStage"], stage)
        self.assertTrue(activation["operationId"].startswith(stage + ":"))

    def test_silence_overall_and_rss_limits_fail_closed(self) -> None:
        cases = (
            (
                "emitter.stopped.set()\ntime.sleep(30)",
                {"silence": 0.2},
                "SILENCE_LIMIT",
            ),
            (
                "emitter.progress('OTHER', {})\ntime.sleep(30)",
                {"overall": 0.2, "silence": 1.0},
                "OVERALL_LIMIT",
            ),
            (
                "emitter.progress('OTHER', {})\ntime.sleep(30)",
                {"rss_bytes": 1},
                "RSS_LIMIT",
            ),
        )
        for body, options, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaises(SupervisionError) as raised:
                    _run(body, **options)
                self.assertEqual(raised.exception.reason, reason)

    def test_unavailable_tree_memory_accounting_fails_closed(self) -> None:
        with mock.patch(
            "server.sports_phase4.supervision._tree_rss",
            side_effect=OSError("fixture accounting failure"),
        ):
            with self.assertRaises(SupervisionError) as raised:
                _run("time.sleep(30)")
        self.assertEqual(raised.exception.reason, "RSS_LIMIT")
        self.assertIn("accounting failed closed", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
