from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel, Field


router = APIRouter()

MAX_CODE_CHARS = int(os.getenv("ATLAS_PYTHON_RUN_MAX_CHARS", "120000"))
TIMEOUT_SECONDS = float(os.getenv("ATLAS_PYTHON_RUN_TIMEOUT_SECONDS", "5"))
RUNTIME_ROOT = Path(os.getenv("ATLAS_PYTHON_RUNTIME_DIR", ".tmp/python-execution")).resolve()
HOSTED_MODE = os.getenv("ATLAS_HOSTED_MODE", "").strip().lower() in {"1", "true", "yes"}
EXECUTION_ENABLED = os.getenv("ATLAS_ENABLE_PYTHON_RUN", "1").strip().lower() not in {"0", "false", "no"} and not HOSTED_MODE


class PythonRunRequest(BaseModel):
    page: str = Field(default="Unknown page")
    userCode: str = Field(default="")
    projectId: str = Field(default="")
    workflowStep: str = Field(default="")


def run_python_request(request: PythonRunRequest) -> Dict[str, Any]:
    if not EXECUTION_ENABLED:
        return {
            "ok": False,
            "status": "unavailable",
            "stdout": "",
            "stderr": "Python execution backend is unavailable. Code will still be included in notebook export.",
            "runtimeMs": 0,
        }

    code = request.userCode or ""
    if not code.strip():
        return {"ok": True, "status": "empty", "stdout": "", "stderr": "No Python code to execute.", "runtimeMs": 0}
    if len(code) > MAX_CODE_CHARS:
        return {
            "ok": False,
            "status": "error",
            "stdout": "",
            "stderr": f"Python code is too large to execute locally. Limit is {MAX_CODE_CHARS:,} characters.",
            "runtimeMs": 0,
        }

    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    temp_dir = RUNTIME_ROOT / f"atlas-python-{uuid.uuid4().hex[:12]}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        script_path = temp_dir / "atlas_step_code.py"
        script_path.write_text(code, encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(temp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SECONDS,
                env=os.environ.copy(),
            )
            runtime_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": completed.returncode == 0,
                "status": "success" if completed.returncode == 0 else "error",
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "runtimeMs": runtime_ms,
                "returnCode": completed.returncode,
            }
        except subprocess.TimeoutExpired as exc:
            runtime_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": False,
                "status": "timeout",
                "stdout": exc.stdout or "",
                "stderr": f"Python execution timed out after {TIMEOUT_SECONDS:g} seconds.",
                "runtimeMs": runtime_ms,
            }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/python/run")
def run_python(request: PythonRunRequest) -> Dict[str, Any]:
    return run_python_request(request)
