"""Headless browser composition coverage for the isolated restart soak.

This companion test intentionally reuses the UUID-scoped backend authority from
``project_context_backend_restart_soak_test.py``. It serves the production
frontend bundle through a disposable Vite preview/proxy and opens a real
Chromium context before the first restart and after every backend process
replacement. No live port, user, project, dataset, or credential is used.

Run the required ten-cycle acceptance:

    .venv/Scripts/python.exe -m pytest -q -s \
        tests/project_context_browser_restart_integration_test.py

For a local harness proof only, ``ATLAS_RESTART_BROWSER_CYCLES=1`` may be set.
The default and acceptance contract remain ten replacement cycles.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOAK_PATH = REPO_ROOT / "tests" / "project_context_backend_restart_soak_test.py"
PLAYWRIGHT_SPEC = (
    REPO_ROOT
    / "tests"
    / "e2e"
    / "project-context-backend-restart.integration.ts"
)
PLAYWRIGHT_CONFIG = (
    REPO_ROOT
    / "tests"
    / "e2e"
    / "project-context-backend-restart.playwright.config.ts"
)
VITE_CONFIG = (
    REPO_ROOT
    / "tests"
    / "e2e"
    / "project-context-backend-restart.vite.config.ts"
)
NODE = shutil.which("node")
VITE_CLI = REPO_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
PLAYWRIGHT_CLI = REPO_ROOT / "node_modules" / "@playwright" / "test" / "cli.js"
DEFAULT_RESTART_CYCLES = 10


def _load_backend_soak_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "atlas_project_context_backend_restart_soak",
        BACKEND_SOAK_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("The backend restart soak helper could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BACKEND_SOAK = _load_backend_soak_module()


class IsolatedFrontend:
    def __init__(self, *, port: int, backend_url: str, log_path: Path) -> None:
        self.port = port
        self.backend_url = backend_url
        self.log_path = log_path
        self.process: subprocess.Popen[bytes] | None = None
        self._log_handle: Any = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> int:
        if NODE is None:
            raise AssertionError("Node.js is unavailable; isolated Vite preview cannot start.")
        if not (REPO_ROOT / "dist" / "index.html").is_file():
            raise AssertionError(
                "The production dist/index.html bundle is unavailable. Run npm run build before "
                "the browser restart integration test."
            )
        if not VITE_CLI.is_file():
            raise AssertionError("The repository Vite CLI is unavailable.")
        environment = os.environ.copy()
        environment["ATLAS_RESTART_BACKEND_URL"] = self.backend_url
        self._log_handle = self.log_path.open("ab")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [
                NODE,
                str(VITE_CLI),
                "preview",
                "--config",
                str(VITE_CONFIG),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--strictPort",
            ],
            cwd=REPO_ROOT,
            env=environment,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(
                    f"Isolated Vite preview exited during startup with code {self.process.returncode}."
                )
            try:
                response = httpx.get(self.url, timeout=1.0)
                if response.status_code == 200:
                    return int(self.process.pid)
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise AssertionError("Isolated Vite preview did not become healthy before the deadline.")

    def stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
            self.process = None
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None


class BrowserRestartIntegration:
    def __init__(self, restart_cycles: int) -> None:
        if restart_cycles < 1:
            raise AssertionError("At least one backend replacement cycle is required.")
        self.restart_cycles = restart_cycles
        self.authority = BACKEND_SOAK.RestartSoak()
        self.frontend_port = BACKEND_SOAK._available_loopback_port()
        while self.frontend_port == self.authority.port:
            self.frontend_port = BACKEND_SOAK._available_loopback_port()
        self.frontend = IsolatedFrontend(
            port=self.frontend_port,
            backend_url=f"http://127.0.0.1:{self.authority.port}",
            log_path=self.authority.runtime_root / "frontend.log",
        )
        self.result_path = (
            self.authority.runtime_root / "browser-restart-integration-result.json"
        )
        self.browser_log_path = self.authority.runtime_root / "playwright.log"
        self.browser_records: list[dict[str, Any]] = []
        self.restart_records: list[dict[str, Any]] = []
        self.started_at = time.time()

    def _session_cookie(self) -> str:
        for cookie in self.authority.client.cookies.jar:
            if cookie.name == "atlas_session":
                return str(cookie.value)
        raise AssertionError("Synthetic registration did not return an authenticated session cookie.")

    def _run_browser_cycle(self, label: str, pid: int) -> None:
        if NODE is None or not PLAYWRIGHT_CLI.is_file():
            raise AssertionError("The repository Playwright runner is unavailable.")
        browser_result = self.authority.runtime_root / f"browser-{label}.json"
        browser_runtime = self.authority.runtime_root / f"playwright-{label}"
        browser_runtime.mkdir(parents=True, exist_ok=False)
        environment = os.environ.copy()
        environment.update(
            {
                "ATLAS_E2E_BASE_URL": self.frontend.url,
                "ATLAS_RESTART_BROWSER_RUNTIME": str(browser_runtime),
                "ATLAS_RESTART_SESSION_COOKIE": self._session_cookie(),
                "ATLAS_RESTART_PROJECT_ID": self.authority.identifiers["project_id"],
                "ATLAS_RESTART_DATASET_ID": self.authority.identifiers["dataset_id"],
                "ATLAS_RESTART_DATASET_VERSION_ID": self.authority.identifiers[
                    "dataset_version_id"
                ],
                "ATLAS_RESTART_ACTIVATION_REVISION": str(
                    self.authority.identifiers["activation_revision"]
                ),
                "ATLAS_RESTART_CYCLE_LABEL": label,
                "ATLAS_RESTART_BROWSER_RESULT_PATH": str(browser_result),
            }
        )
        completed = subprocess.run(
            [
                NODE,
                str(PLAYWRIGHT_CLI),
                "test",
                PLAYWRIGHT_SPEC.name,
                "--config",
                str(PLAYWRIGHT_CONFIG),
                "--project",
                "chromium",
            ],
            cwd=REPO_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=150,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = completed.stdout.decode("utf-8", errors="replace")
        # The runner is not expected to emit the cookie, but redact defensively
        # before retaining any subprocess diagnostic.
        output = output.replace(self._session_cookie(), "[synthetic-session-redacted]")
        with self.browser_log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n[{label}] pid={pid} exit={completed.returncode}\n")
            log.write(output[-12000:])
        if completed.returncode != 0:
            raise AssertionError(
                f"Actual Chromium composition failed for {label}; "
                f"safe runner tail: {output[-2400:]}"
            )
        if not browser_result.is_file():
            raise AssertionError(f"Chromium composition for {label} produced no result artifact.")
        result = json.loads(browser_result.read_text(encoding="utf-8"))
        assert result["status"] == "passed"
        assert result["cycle_label"] == label
        assert result["project_id"] == self.authority.identifiers["project_id"]
        assert result["dataset_id"] == self.authority.identifiers["dataset_id"]
        assert (
            result["dataset_version_id"]
            == self.authority.identifiers["dataset_version_id"]
        )
        assert int(result["activation_revision"]) == int(
            self.authority.identifiers["activation_revision"]
        )
        assert result["step00"]["mounts"] == 1
        assert result["step00"]["unmounts"] == 0
        assert result["step00"]["project_context_events"] == 0
        assert result["step01"]["exact_identity_rendered"] is True
        assert result["step02"]["overview_status"] == 200
        assert result["step02"]["final_holdout_accessed"] is False
        assert result["step02"]["final_holdout_used_for_selection"] is False
        assert result["forbidden_request_count"] == 0
        assert result["final_holdout_data_request_count"] == 0
        assert result["authority_mutation_request_count"] == 0
        result["backend_pid"] = pid
        self.browser_records.append(result)

    def _write_result(self, status: str, error: BaseException | None = None) -> None:
        payload = {
            "status": status,
            "runtime_seconds": round(time.time() - self.started_at, 3),
            "restart_cycles_required": self.restart_cycles,
            "restart_cycles_completed": len(self.restart_records),
            "browser_composition_passes": len(self.browser_records),
            "expected_browser_composition_passes": self.restart_cycles + 1,
            "identifiers": self.authority.identifiers,
            "frontend_port": self.frontend_port,
            "backend_port": self.authority.port,
            "restart_records": self.restart_records,
            "browser_records": self.browser_records,
            "live_heloc_authority_used": False,
            "training_performed": False,
            "evaluation_opened": False,
            "interpretation_opened": False,
            "scoring_performed": False,
            "final_holdout_accessed": False,
            "forbidden_routes_called": [],
            "error": (
                f"{type(error).__name__}: {str(error)[:1200]}" if error else None
            ),
        }
        temporary = self.result_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(self.result_path)

    def run(self) -> None:
        current_pid: int | None = None
        failure: BaseException | None = None
        try:
            current_pid = self.authority.backend.start()
            self.authority.create_fixture()
            self.frontend.start()

            self.authority.verify_continuity("browser-baseline", current_pid)
            self._run_browser_cycle("baseline", current_pid)

            for cycle in range(1, self.restart_cycles + 1):
                old_pid = current_pid
                stopped = self.authority.backend.stop()
                assert stopped["pid"] == old_pid
                assert stopped["listener_stopped"] is True
                current_pid = self.authority.backend.start()
                assert current_pid != old_pid
                assert self.authority.backend.process is not None
                assert self.authority.backend.process.poll() is None
                record = {
                    "cycle": cycle,
                    "old_pid": old_pid,
                    "old_listener_stopped": True,
                    "old_exit_code": stopped["exit_code"],
                    "new_pid": current_pid,
                    "new_listener_healthy": True,
                }
                self.restart_records.append(record)
                self.authority.verify_continuity(f"browser-restart-{cycle}", current_pid)
                self._run_browser_cycle(f"restart-{cycle}", current_pid)

            assert len(self.restart_records) == self.restart_cycles
            assert len(self.browser_records) == self.restart_cycles + 1
            assert len({record["backend_pid"] for record in self.browser_records}) == (
                self.restart_cycles + 1
            )
            assert all(
                record["old_pid"] != record["new_pid"]
                for record in self.restart_records
            )
        except BaseException as exc:
            failure = exc
            raise
        finally:
            self.frontend.stop()
            self.authority.backend.stop()
            self.authority.client.close()
            self._write_result("failed" if failure else "passed", failure)
            print(f"browser_restart_integration_result={self.result_path}")
            print(f"browser_restart_integration_log={self.browser_log_path}")


def test_actual_browser_composition_survives_backend_restarts() -> None:
    configured = os.getenv("ATLAS_RESTART_BROWSER_CYCLES", "").strip()
    restart_cycles = int(configured) if configured else DEFAULT_RESTART_CYCLES
    BrowserRestartIntegration(restart_cycles).run()


if __name__ == "__main__":
    test_actual_browser_composition_survives_backend_restarts()
