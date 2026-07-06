from __future__ import annotations

import os
import json
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
    context: Dict[str, Any] = Field(default_factory=dict)


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
        context_code = ""
        if request.context:
            context_code = (
                "# ATLAS execution context injected for local development.\n"
                f"ATLAS_CONTEXT = {json.dumps(request.context)}\n"
                "preview_rows = ATLAS_CONTEXT.get('preview_rows', [])\n"
                "primary_preview_rows = ATLAS_CONTEXT.get('primary_preview_rows', preview_rows)\n"
                "secondary_preview_rows = ATLAS_CONTEXT.get('secondary_preview_rows', [])\n"
                "dataset_name = ATLAS_CONTEXT.get('dataset_name', '')\n"
                "version_id = ATLAS_CONTEXT.get('version_id', '')\n\n"
                "try:\n"
                "    import pandas as pd\n"
                "    df = pd.DataFrame(preview_rows)\n"
                "except BaseException as ATLAS_PANDAS_ERROR:\n"
                "    pd = None\n"
                "    class ATLASPreviewFrame(list):\n"
                "        @property\n"
                "        def shape(self):\n"
                "            cols = len(self[0].keys()) if self and isinstance(self[0], dict) else 0\n"
                "            return (len(self), cols)\n"
                "        def head(self, n=5):\n"
                "            return list(self[:n])\n"
                "        def describe(self, *args, **kwargs):\n"
                "            return {'rows': len(self), 'columns': self.shape[1]}\n"
                "    df = ATLASPreviewFrame(preview_rows)\n"
                "    print(f'ATLAS warning: pandas is unavailable or failed to initialize: {ATLAS_PANDAS_ERROR}')\n\n"
            )
        script_path.write_text(context_code + code, encoding="utf-8")
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
