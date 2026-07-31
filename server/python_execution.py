from __future__ import annotations

import os
import json
import shutil
import shlex
import subprocess
import sys
import time
import uuid
import platform
import tempfile
import csv
import re
import importlib.util
import importlib.metadata
import urllib.request
from pathlib import Path
from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .core.modeling_scope import authorize_modeling_scope
from .datasets.dataset_identity import (
    active_dataset_identity,
    assert_expected_active_identity,
)
from .security.security_store import require_user

from .code_execution.sas_compatible import SUPPORTED_PROCS, run_sas_compatible
from .code_execution import sandbox_policy
from .code_execution.dataset_binding import (
    build_runtime_prelude,
    resolve_bound_dataset,
    runtime_contract_description,
    stage_dataset_for_sandbox,
)


router = APIRouter()

#: Bound on captured stream text so a runaway loop cannot flood the response.
MAX_STREAM_CHARS = int(os.getenv("ATLAS_PYTHON_RUN_MAX_OUTPUT_CHARS", "200000"))


def _bounded(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_STREAM_CHARS:
        return text, False
    return text[:MAX_STREAM_CHARS], True


def _describe_failure(stderr: str) -> Dict[str, Any] | None:
    """Extracts the exception type, message, and failing source line from a
    traceback so the UI can report what stopped execution.

    Derived generically from the traceback -- nothing is special-cased for any
    particular program or assertion.
    """
    if not stderr.strip():
        return None
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    exception_line = lines[-1] if lines else ""
    exception_type, _, exception_message = exception_line.partition(":")
    exception_type = exception_type.strip()
    exception_message = exception_message.strip()

    failed_line_number: int | None = None
    failed_source = ""
    for index, line in enumerate(lines):
        marker = re.search(r'File "(?:[^"]*)", line (\d+)', line)
        if marker:
            failed_line_number = int(marker.group(1))
            # The source excerpt follows its File/line header when available.
            if index + 1 < len(lines) and not lines[index + 1].lstrip().startswith('File "'):
                failed_source = lines[index + 1].strip()

    explanation = ""
    if exception_type == "AssertionError":
        explanation = (
            "The program ran and produced output, but a user assertion did not hold. "
            "The computed value did not match the value the assertion expected."
        )
    return {
        "exceptionType": exception_type or "Error",
        "exceptionMessage": exception_message,
        "failedLineNumber": failed_line_number,
        "failedSource": failed_source,
        "explanation": explanation,
    }

MAX_CODE_CHARS = int(os.getenv("ATLAS_PYTHON_RUN_MAX_CHARS", "120000"))
# The governed prelude imports pandas and loads the staged dataset before user
# code runs; a cold `import pandas` alone measures ~8 s on a developer machine,
# so a 5 s budget made every dataframe program time out. Still bounded and still
# enforced by subprocess timeout + process termination.
TIMEOUT_SECONDS = float(os.getenv("ATLAS_PYTHON_RUN_TIMEOUT_SECONDS", "60"))
#: Separate, shorter budget for the diagnostics probes, which must stay responsive.
DIAGNOSTIC_TIMEOUT_SECONDS = float(os.getenv("ATLAS_PYTHON_DIAGNOSTIC_TIMEOUT_SECONDS", "30"))
RUNTIME_ROOT = Path(os.getenv("ATLAS_PYTHON_RUNTIME_DIR", ".tmp/python-execution")).resolve()
HOSTED_MODE = os.getenv("ATLAS_HOSTED_MODE", "").strip().lower() in {"1", "true", "yes"}
EXECUTION_ENABLED = os.getenv("ATLAS_ENABLE_PYTHON_RUN", "1").strip().lower() not in {"0", "false", "no"} and not HOSTED_MODE
SANDBOX_COMMAND = os.getenv("ATLAS_CODE_SANDBOX_COMMAND", "").strip()
SAS_CONFIG_DIR = Path(os.getenv("ATLAS_SAS_CONFIG_DIR", "server/artifacts/config")).resolve()
SAS_CONFIG_PATH = SAS_CONFIG_DIR / "sas_runtime.json"
SAS_CONFIG_EXAMPLE_PATH = SAS_CONFIG_DIR / "sas_runtime.example.json"
SAFE_CFG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
SAFE_ENV_KEYS = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "R_HOME",
    "R_LIBS_USER",
    "SAS_CONFIG_NAME",
    "SASPY_CONFIG_PATH",
    "ATLAS_SAS_CFGNAME",
    "ATLAS_SAS_CFGFILE",
}


class PythonRunRequest(BaseModel):
    page: str = Field(default="Unknown page")
    userCode: str = Field(default="")
    projectId: str = Field(default="")
    workflowStep: str = Field(default="")
    context: Dict[str, Any] = Field(default_factory=dict)
    captureImages: bool = Field(default=False)


class CodeRunRequest(BaseModel):
    code: str = Field(default="")
    context: Dict[str, Any] = Field(default_factory=dict)


class QuestionCleanupRequest(BaseModel):
    text: str = Field(default="")
    context: Dict[str, Any] = Field(default_factory=dict)


class SasSettingsRequest(BaseModel):
    cfgname: str = Field(default="")
    cfgfile: str = Field(default="")
    executionMode: Literal["template_only", "saspy_config", "external_export"] = Field(default="template_only")


def execution_env() -> Dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV_KEYS}
    env["ATLAS_CODE_EXECUTION"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def sandbox_command(script_path: Path, workdir: Path) -> list[str] | None:
    """Legacy helper retained for the R path. Delegates to the approved-command
    policy so R execution inherits the same allowlist and argument-vector rules
    as Python -- it no longer splits an arbitrary shell string."""
    try:
        return sandbox_policy.resolve_sandbox_command(
            os.getenv("ATLAS_CODE_SANDBOX_COMMAND", "").strip(), script_path, workdir
        )
    except sandbox_policy.SandboxPolicyError:
        return None


def run_python_request(request: PythonRunRequest) -> Dict[str, Any]:
    # Capability is resolved per request (not at import time) so a deployment can
    # configure the sandbox without restarting, and so the UI and the executor
    # always agree about what is possible.
    capability = sandbox_policy.describe_capability()
    if not capability.available:
        return {
            "ok": False,
            "status": "unavailable",
            "runtimeState": capability.state,
            "stdout": "",
            "stderr": capability.reason,
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
        context = request.context or {}

        # CODE-DATAACQ-002: bind to the exact authorized dataset version instead
        # of emitting an unresolvable placeholder path. The artifact is resolved
        # server-side and staged read-only inside this run's isolated workdir.
        bound = resolve_bound_dataset(
            dataset_id=str(context.get("datasetId") or ""),
            version_id=str(context.get("versionId") or ""),
            target=str(context.get("target") or ""),
            selected_features=list(context.get("selectedFeatures") or []),
        )
        staged_path = stage_dataset_for_sandbox(bound, temp_dir) if bound else None
        preview_rows = context.get("previewRows") or context.get("preview_rows") or []
        context_code = build_runtime_prelude(
            bound,
            staged_path,
            preview_rows=preview_rows if isinstance(preview_rows, list) else [],
            target=str(context.get("target") or ""),
            selected_features=list(context.get("selectedFeatures") or []),
            context=context,
        )
        capture_images = bool(request.captureImages or request.page == "Notebook Studio")
        plot_prelude = ""
        plot_postlude = ""
        if capture_images:
            plot_prelude = (
                "# ATLAS notebook image capture. Local development only.\n"
                "ATLAS_IMAGE_OUTPUTS = []\n"
                "ATLAS_TABLE_OUTPUTS = []\n"
                "def atlas_display(value, title='ATLAS table output'):\n"
                "    try:\n"
                "        if hasattr(value, 'head'):\n"
                "            value = value.head(100)\n"
                "        if hasattr(value, 'to_dict'):\n"
                "            rows = value.to_dict(orient='records')\n"
                "            columns = [str(col) for col in getattr(value, 'columns', [])]\n"
                "        elif isinstance(value, list):\n"
                "            rows = value[:100]\n"
                "            columns = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []\n"
                "        else:\n"
                "            rows = [{'value': str(value)}]\n"
                "            columns = ['value']\n"
                "        ATLAS_TABLE_OUTPUTS.append({'title': title, 'columns': columns, 'rows': rows})\n"
                "        print(f'ATLAS displayed table: {title} ({len(rows)} rows)')\n"
                "    except BaseException as atlas_display_error:\n"
                "        print(f'ATLAS table display warning: {atlas_display_error}')\n"
                "try:\n"
                "    import matplotlib\n"
                "    matplotlib.use('Agg', force=True)\n"
                "except BaseException:\n"
                "    pass\n\n"
            )
            plot_postlude = (
                "\n\n# ATLAS captures matplotlib figures after user code runs.\n"
                "try:\n"
                "    import io, base64, json as _atlas_json\n"
                "    import matplotlib.pyplot as plt\n"
                "    for _atlas_index, _atlas_num in enumerate(plt.get_fignums()[:5], start=1):\n"
                "        _atlas_fig = plt.figure(_atlas_num)\n"
                "        _atlas_buffer = io.BytesIO()\n"
                "        _atlas_fig.savefig(_atlas_buffer, format='png', bbox_inches='tight', dpi=144)\n"
                "        _atlas_data = base64.b64encode(_atlas_buffer.getvalue()).decode('ascii')\n"
                "        if len(_atlas_data) <= 1500000:\n"
                "            ATLAS_IMAGE_OUTPUTS.append({'mimeType': 'image/png', 'data': _atlas_data, 'alt': f'matplotlib output {_atlas_index}'})\n"
                "    plt.close('all')\n"
                "    print('ATLAS_IMAGE_OUTPUTS_JSON:' + _atlas_json.dumps(ATLAS_IMAGE_OUTPUTS))\n"
                "    print('ATLAS_TABLE_OUTPUTS_JSON:' + _atlas_json.dumps(ATLAS_TABLE_OUTPUTS, default=str))\n"
                "except BaseException as _atlas_plot_error:\n"
                "    import sys as _atlas_sys\n"
                "    print(f'ATLAS plot capture warning: {_atlas_plot_error}', file=_atlas_sys.stderr)\n"
            )
        script_path.write_text(context_code + plot_prelude + code + plot_postlude, encoding="utf-8")
        try:
            try:
                command = sandbox_policy.resolve_sandbox_command(
                    os.getenv("ATLAS_CODE_SANDBOX_COMMAND", "").strip(), script_path, temp_dir
                )
            except sandbox_policy.SandboxPolicyError as exc:
                return {
                    "ok": False,
                    "status": "unavailable",
                    "runtimeState": "misconfigured",
                    "stdout": "",
                    "stderr": "Python execution is unavailable because the configured code sandbox is not approved for this ATLAS environment.",
                    "detail": str(exc),
                    "runtimeMs": int((time.perf_counter() - started) * 1000),
                }
            completed = subprocess.run(
                command,
                cwd=str(temp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SECONDS,
                env=execution_env(),
            )
            runtime_ms = int((time.perf_counter() - started) * 1000)
            stdout = completed.stdout or ""
            images = []
            tables = []
            image_sentinel = "ATLAS_IMAGE_OUTPUTS_JSON:"
            table_sentinel = "ATLAS_TABLE_OUTPUTS_JSON:"
            if image_sentinel in stdout or table_sentinel in stdout:
                cleaned_lines = []
                for line in stdout.splitlines():
                    if line.startswith(image_sentinel):
                        try:
                            images = json.loads(line[len(image_sentinel) :])
                        except Exception:
                            images = []
                    elif line.startswith(table_sentinel):
                        try:
                            tables = json.loads(line[len(table_sentinel) :])
                        except Exception:
                            tables = []
                    else:
                        cleaned_lines.append(line)
                stdout = "\n".join(cleaned_lines)
                if completed.stdout.endswith("\n") and stdout:
                    stdout += "\n"
            bounded_stdout, stdout_truncated = _bounded(stdout)
            bounded_stderr, stderr_truncated = _bounded(completed.stderr or "")
            failure = _describe_failure(bounded_stderr) if completed.returncode != 0 else None
            # PYTHON-TEST-001 / Part J: valid stdout must never imply success.
            # A program that printed results and then failed is reported as
            # "failed after producing output", with the failing line isolated.
            produced_output = bool(bounded_stdout.strip())
            return {
                "ok": completed.returncode == 0,
                "status": "success" if completed.returncode == 0 else "error",
                "failurePhase": "user_code" if completed.returncode != 0 else None,
                "outcome": (
                    "completed"
                    if completed.returncode == 0
                    else "failed_after_output" if produced_output else "failed"
                ),
                "failure": failure,
                "runtimeState": "executable",
                "stdout": bounded_stdout,
                "stderr": bounded_stderr,
                "truncated": stdout_truncated or stderr_truncated,
                "runtimeMs": runtime_ms,
                "returnCode": completed.returncode,
                "runtimeContract": runtime_contract_description(bound),
                "datasetId": bound.dataset_id if bound else "",
                "versionId": bound.version_id if bound else "",
                "images": images[:5],
                "tables": tables[:5],
                "rows": (tables[0].get("rows") if tables and isinstance(tables[0], dict) else []),
                "columns": (tables[0].get("columns") if tables and isinstance(tables[0], dict) else []),
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
def run_python(request: PythonRunRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    # Execution is scoped to a project the caller may actually view. Without this
    # an authenticated user could run code bound to another project's dataset.
    if request.projectId:
        authorize_modeling_scope(user, request.projectId, "view")
        context = request.context or {}
        requested_dataset_id = str(context.get("datasetId") or "").strip()
        requested_version_id = str(context.get("versionId") or "").strip()
        try:
            active_dataset_identity(
                request.projectId,
                user=user,
            )
        except HTTPException:
            # A workspace draft may execute only preview-bound code. If a
            # caller claims governed identity, it must resolve exactly.
            if requested_dataset_id or requested_version_id:
                raise
        else:
            # Once the project has a governed dataset, omitting its identity
            # would downgrade execution to ungoverned preview rows.
            assert_expected_active_identity(
                request.projectId,
                expected_dataset_id=requested_dataset_id,
                expected_dataset_version_id=requested_version_id,
                require_expected=True,
                user=user,
            )
    return run_python_request(request)


@router.get("/python/environment")
def python_environment(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Read-only inventory of the governed analytical environment (PYENV-001).

    Versions are read from the live interpreter, so a package is never claimed
    installed without being present. No filesystem paths or secrets are exposed.
    """
    from .code_execution.environment_inventory import build_environment_inventory

    return build_environment_inventory()


@router.get("/python/capability")
def python_capability(user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Authoritative Python execution capability for the UI.

    Ordinary users receive the state and a non-sensitive explanation. Admins
    additionally receive the missing configuration key and approved interpreters,
    so operators can diagnose without leaking server command detail to everyone.
    """
    capability = sandbox_policy.describe_capability()
    is_admin = str(user.get("role") or "").lower() == "admin"
    payload = capability.admin_dict() if is_admin else capability.public_dict()
    return {"ok": True, **payload}


@router.post("/llm/cleanup-question")
def cleanup_question(request: QuestionCleanupRequest) -> Dict[str, Any]:
    original = (request.text or "").strip()
    if not original:
        return {"ok": False, "cleanedText": "", "source": "deterministic", "message": "Enter rough question language before cleanup."}
    endpoint = os.getenv("ATLAS_LLM_ENDPOINT", "").strip()
    if endpoint:
        try:
            payload = json.dumps({"text": original, "context": request.context or {}}).encode("utf-8")
            http_request = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(http_request, timeout=TIMEOUT_SECONDS) as response:
                body = json.loads(response.read().decode("utf-8"))
            cleaned = str(body.get("cleanedText") or body.get("text") or body.get("result") or "").strip()
            if cleaned:
                return {"ok": True, "cleanedText": cleaned, "source": "llm", "message": "Question cleaned up using configured ATLAS LLM endpoint."}
        except Exception:
            pass
    target = str((request.context or {}).get("targetColumn") or "the selected target")
    return {
        "ok": True,
        "cleanedText": deterministic_question_cleanup(original, target),
        "source": "deterministic",
        "message": "Question cleaned up using deterministic ATLAS cleanup.",
    }


@router.post("/code/r/run")
def run_r(request: CodeRunRequest) -> Dict[str, Any]:
    started = time.perf_counter()
    if not SANDBOX_COMMAND:
        return {
            "ok": False,
            "status": "unavailable",
            "stdout": "",
            "stderr": "R execution is disabled until ATLAS_CODE_SANDBOX_COMMAND points to an approved OS/container sandbox.",
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "returnCode": None,
            "diagnostics": {"rscriptDetected": bool(shutil.which("Rscript")), "rscriptPath": shutil.which("Rscript") or ""},
        }
    rscript = shutil.which("Rscript")
    if not rscript:
        return {
            "ok": False,
            "status": "unavailable",
            "stdout": "",
            "stderr": "R execution is not configured on this machine. Install R and ensure Rscript is on PATH to enable local R execution.",
            "runtimeMs": 0,
            "returnCode": None,
            "diagnostics": {"rscriptDetected": False, "rscriptPath": ""},
        }
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = RUNTIME_ROOT / f"atlas-r-{uuid.uuid4().hex[:12]}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        rows = request.context.get("previewRows") or request.context.get("preview_rows") or []
        csv_path = temp_dir / "atlas_preview.csv"
        write_preview_csv(csv_path, rows if isinstance(rows, list) else [])
        script_path = temp_dir / "atlas_code.R"
        prelude = (
            "# ATLAS runtime prelude\n"
            f"df <- read.csv({json.dumps(str(csv_path).replace(chr(92), '/'))}, stringsAsFactors = FALSE)\n"
            "cat(\"ATLAS R smoke test passed.\\n\")\n"
            "cat(\"Rows:\", nrow(df), \" Columns:\", ncol(df), \"\\n\")\n"
            "print(head(df))\n\n"
        )
        script_path.write_text(prelude + (request.code or ""), encoding="utf-8")
        command = sandbox_command(script_path, temp_dir)
        if not command:
            return {
                "ok": False,
                "status": "unavailable",
                "stdout": "",
                "stderr": "R execution is disabled because no approved sandbox command is configured.",
                "runtimeMs": int((time.perf_counter() - started) * 1000),
                "returnCode": None,
            }
        completed = subprocess.run(
            command,
            cwd=str(temp_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            env=execution_env(),
        )
        return {
            "ok": completed.returncode == 0,
            "status": "success" if completed.returncode == 0 else "error",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "returnCode": completed.returncode,
            "diagnostics": {"rscriptDetected": True, "rscriptPath": rscript},
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "status": "timeout",
            "stdout": exc.stdout or "",
            "stderr": f"R execution timed out after {TIMEOUT_SECONDS:g} seconds.",
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "returnCode": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "stdout": "",
            "stderr": f"ATLAS could not execute R code: {exc}",
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "returnCode": None,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/code/sas/run")
def run_sas(request: CodeRunRequest) -> Dict[str, Any]:
    started = time.perf_counter()
    diagnostics = sas_diagnostics()
    settings = load_sas_runtime_settings()
    if settings.get("executionMode") != "saspy_config":
        return {
            "ok": True,
            "status": "template",
            "log": "",
            "listing": "SAS template validated. SAS execution is not configured. Use this code in your external SAS environment, or configure SASPy to run SAS inside ATLAS.",
            "stdout": "SAS template validated. SAS execution is not configured. Use this code in your external SAS environment, or configure SASPy to run SAS inside ATLAS.",
            "stderr": "",
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "diagnostics": diagnostics,
        }
    if not diagnostics["sasExecutionAvailable"]:
        return {
            "ok": False,
            "status": "unavailable",
            "log": diagnostics.get("lastError") or "SAS execution setup is incomplete. Save SAS runtime settings and run Test SAS Connection before executing SAS code.",
            "listing": "",
            "stdout": "",
            "stderr": diagnostics.get("lastError") or "SAS execution setup is incomplete.",
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "diagnostics": diagnostics,
        }
    try:
        import pandas as pd  # type: ignore
        import saspy  # type: ignore

        rows = request.context.get("previewRows") or request.context.get("preview_rows") or []
        df = pd.DataFrame(rows if isinstance(rows, list) else [])
        sas = start_sas_session(settings)
        try:
            table_name = safe_sas_name(str(request.context.get("datasetName") or "atlas_preview"))
            sas.df2sd(df, table=table_name, libref="work")
            result = sas.submit(request.code or "")
            return {
                "ok": True,
                "status": "success",
                "log": result.get("LOG", ""),
                "listing": result.get("LST", ""),
                "stdout": result.get("LST", ""),
                "stderr": result.get("LOG", ""),
                "runtimeMs": int((time.perf_counter() - started) * 1000),
                "diagnostics": diagnostics,
            }
        finally:
            try:
                sas.endsas()
            except Exception:
                pass
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "log": f"ATLAS could not execute SAS code: {exc}",
            "listing": "",
            "stdout": "",
            "stderr": str(exc),
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "diagnostics": diagnostics,
        }


@router.post("/code/sas-compatible/run")
def run_sas_compatible_endpoint(request: CodeRunRequest) -> Dict[str, Any]:
    return run_sas_compatible(request.code or "", request.context or {})


@router.get("/code/sas/diagnostics")
def get_sas_diagnostics() -> Dict[str, Any]:
    return {"ok": True, **sas_diagnostics()}


@router.post("/code/sas/settings")
def save_sas_settings(request: SasSettingsRequest) -> Dict[str, Any]:
    cfgname = request.cfgname.strip()
    cfgfile = request.cfgfile.strip()
    if cfgname and not SAFE_CFG_RE.match(cfgname):
        return {"ok": False, "status": "error", "detail": "SASPy cfgname must start with a letter or underscore and contain only letters, numbers, underscores, or hyphens."}
    if cfgfile and not Path(cfgfile).expanduser().exists():
        return {"ok": False, "status": "error", "detail": f"SASPy cfgfile path was not found: {cfgfile}"}
    settings = {
        "cfgname": cfgname,
        "cfgfile": str(Path(cfgfile).expanduser()) if cfgfile else "",
        "executionMode": request.executionMode,
        "updatedAt": now_iso(),
        "updatedBy": "local_user",
        "lastConnectionOk": False,
        "lastConnectionTestedAt": "",
        "lastConnectionError": "",
    }
    write_sas_runtime_settings(settings)
    return {"ok": True, "settings": settings, "diagnostics": sas_diagnostics()}


@router.post("/code/sas/test-connection")
def test_sas_connection() -> Dict[str, Any]:
    started = time.perf_counter()
    settings = load_sas_runtime_settings()
    if settings.get("executionMode") != "saspy_config":
        settings["lastConnectionOk"] = False
        settings["lastConnectionTestedAt"] = now_iso()
        settings["lastConnectionError"] = "SAS execution mode is template-only or external export. Select SASPy configured session to test an ATLAS-managed SAS connection."
        write_sas_runtime_settings(settings)
        return {
            "ok": True,
            "status": "template",
            "log": "",
            "listing": settings["lastConnectionError"],
            "stdout": settings["lastConnectionError"],
            "stderr": "",
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "diagnostics": sas_diagnostics(),
        }
    try:
        import saspy  # noqa: F401  # type: ignore

        sas = start_sas_session(settings)
        try:
            result = sas.submit(
                "%put ATLAS SAS smoke test passed;\n"
                "data work.atlas_smoke;\n"
                "    x = 1;\n"
                "run;\n\n"
                "proc print data=work.atlas_smoke;\n"
                "run;\n"
            )
            log = result.get("LOG", "")
            listing = result.get("LST", "")
            settings["lastConnectionOk"] = True
            settings["lastConnectionTestedAt"] = now_iso()
            settings["lastConnectionError"] = ""
            write_sas_runtime_settings(settings)
            return {
                "ok": True,
                "status": "success",
                "log": log,
                "listing": listing or "SAS connection test succeeded.",
                "stdout": listing or "SAS connection test succeeded.",
                "stderr": log,
                "runtimeMs": int((time.perf_counter() - started) * 1000),
                "diagnostics": sas_diagnostics(),
            }
        finally:
            try:
                sas.endsas()
            except Exception:
                pass
    except Exception as exc:
        settings["lastConnectionOk"] = False
        settings["lastConnectionTestedAt"] = now_iso()
        settings["lastConnectionError"] = sanitize_error(str(exc))
        write_sas_runtime_settings(settings)
        return {
            "ok": False,
            "status": "error",
            "log": f"SAS connection test failed: {sanitize_error(str(exc))}",
            "listing": "",
            "stdout": "",
            "stderr": sanitize_error(str(exc)),
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "diagnostics": sas_diagnostics(),
        }


@router.get("/python/diagnostics")
def python_diagnostics() -> Dict[str, Any]:
    warnings = []
    temp_probe = None
    can_write_temp = False
    can_capture_stdout = False
    can_capture_stderr = False
    can_start_python = False
    can_import_site = False
    can_import_pandas = False
    rscript_path = shutil.which("Rscript")
    r_can_run = False
    r_version = ""
    sas_info = sas_diagnostics()

    try:
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=str(RUNTIME_ROOT), suffix=".txt") as handle:
            temp_probe = handle.name
            handle.write("atlas")
        can_write_temp = Path(temp_probe).exists()
    except Exception as exc:
        warnings.append(f"Temp file probe failed: {exc}")
    finally:
        if temp_probe:
            Path(temp_probe).unlink(missing_ok=True)

    try:
        completed = subprocess.run(
            [sys.executable, "-c", "import site, sys; print('stdout-ok'); print('stderr-ok', file=sys.stderr)"],
            cwd=str(RUNTIME_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DIAGNOSTIC_TIMEOUT_SECONDS,
            env=execution_env(),
        )
        can_start_python = completed.returncode == 0
        can_import_site = completed.returncode == 0
        can_capture_stdout = "stdout-ok" in completed.stdout
        can_capture_stderr = "stderr-ok" in completed.stderr
        if completed.returncode != 0:
            warnings.append(completed.stderr.strip() or "Python subprocess returned a non-zero status.")
    except Exception as exc:
        warnings.append(f"Python subprocess probe failed: {exc}")

    try:
        pandas_probe = subprocess.run(
            [sys.executable, "-c", "import pandas; print(pandas.__version__)"],
            cwd=str(RUNTIME_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DIAGNOSTIC_TIMEOUT_SECONDS,
            env=execution_env(),
        )
        can_import_pandas = pandas_probe.returncode == 0
        if pandas_probe.returncode != 0:
            warnings.append(f"pandas import probe failed: {pandas_probe.stderr.strip()}")
    except Exception as exc:
        warnings.append(f"pandas probe failed: {exc}")

    if rscript_path:
        try:
            r_probe = subprocess.run(
                [rscript_path, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SECONDS,
            env=execution_env(),
            )
            r_can_run = r_probe.returncode == 0
            r_version = (r_probe.stdout or r_probe.stderr).strip()
        except Exception as exc:
            warnings.append(f"Rscript probe failed: {exc}")

    capability = sandbox_policy.describe_capability()
    return {
        "ok": True,
        "pythonExecutionState": capability.state,
        "pythonExecutionAvailable": capability.available,
        "pythonExecutionReason": capability.reason,
        "pythonSandboxConfigurationKey": capability.configuration_key,
        "pythonSandboxDetail": capability.detail,
        "pythonExecutable": sys.executable,
        "pythonVersion": sys.version,
        "platform": platform.platform(),
        "cwd": os.getcwd(),
        "runtimeRoot": str(RUNTIME_ROOT),
        "runtimeRootExists": RUNTIME_ROOT.exists(),
        "canStartPython": can_start_python,
        "canImportSite": can_import_site,
        "canImportPandas": can_import_pandas,
        "canWriteTempFile": can_write_temp,
        "canCaptureStdout": can_capture_stdout,
        "canCaptureStderr": can_capture_stderr,
        "rscriptDetected": bool(rscript_path),
        "rscriptPath": rscript_path or "",
        "rVersion": r_version,
        "rExecutionAvailable": bool(rscript_path and r_can_run),
        "saspyInstalled": sas_info["saspyInstalled"],
        "saspyVersion": sas_info.get("saspyVersion", ""),
        "saspyModulePath": sas_info.get("saspyModulePath", ""),
        "sasConfigurationFound": sas_info["sasConfigurationFound"],
        "sasConfigFound": sas_info["sasConfigFound"],
        "sasExecutionMode": sas_info["sasExecutionMode"],
        "sasActiveCfgName": sas_info.get("activeCfgName", ""),
        "sasActiveCfgFile": sas_info.get("activeCfgFile", ""),
        "sasCanStartSession": sas_info.get("sasCanStartSession", False),
        "sasLastError": sas_info.get("lastError", ""),
        "sasDetectedConfigFiles": sas_info.get("detectedConfigFiles", []),
        "sasDetectedConfigNames": sas_info.get("detectedConfigNames", []),
        "sasSetupGuidance": sas_info.get("setupGuidance", []),
        "sasExecutionAvailable": sas_info["sasExecutionAvailable"],
        "sasCompatibleAvailable": sas_info["sasCompatibleAvailable"],
        "sasCompatibleSupportedProcs": sas_info["sasCompatibleSupportedProcs"],
        "environmentWarnings": warnings,
    }


def write_preview_csv(path: Path, rows: list[Any]) -> None:
    dict_rows = [row for row in rows if isinstance(row, dict)]
    columns = sorted({str(key) for row in dict_rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in dict_rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def sas_diagnostics() -> Dict[str, Any]:
    ensure_sas_config_files()
    settings = load_sas_runtime_settings()
    saspy_installed = False
    saspy_version = ""
    saspy_module_path = ""
    try:
        spec = importlib.util.find_spec("saspy")
        saspy_installed = spec is not None
        saspy_module_path = str(spec.origin or "") if spec else ""
        if saspy_installed:
            try:
                saspy_version = importlib.metadata.version("saspy")
            except Exception:
                saspy_version = "installed"
    except Exception:
        saspy_installed = False

    detected_files = detect_sas_config_files()
    detected_names = detect_sas_config_names(detected_files)
    env_cfgname = os.getenv("ATLAS_SAS_CFGNAME") or os.getenv("SAS_CONFIG_NAME") or ""
    env_cfgfile = os.getenv("ATLAS_SAS_CFGFILE") or os.getenv("SASPY_CONFIG_PATH") or ""
    env_mode = os.getenv("ATLAS_SAS_EXECUTION_MODE") or ""
    execution_mode = env_mode if env_mode in {"template_only", "saspy_config", "external_export"} else str(settings.get("executionMode") or "template_only")
    active_cfgname = env_cfgname or str(settings.get("cfgname") or "")
    active_cfgfile = env_cfgfile or str(settings.get("cfgfile") or "")
    config_found = bool(active_cfgname or active_cfgfile or detected_files)
    last_ok = bool(settings.get("lastConnectionOk")) and execution_mode == "saspy_config"
    last_error = str(settings.get("lastConnectionError") or "")
    if execution_mode == "saspy_config" and saspy_installed and not last_ok and not last_error:
        last_error = "SASPy is installed, but no successful SAS connection test has been recorded."
    return {
        "saspyInstalled": saspy_installed,
        "saspyVersion": saspy_version,
        "saspyModulePath": saspy_module_path,
        "detectedConfigFiles": detected_files,
        "detectedConfigNames": detected_names,
        "activeCfgName": active_cfgname,
        "activeCfgFile": active_cfgfile,
        "sasConfigFound": config_found,
        "sasConfigurationFound": config_found,
        "sasCanStartSession": last_ok,
        "sasExecutionAvailable": bool(saspy_installed and execution_mode == "saspy_config" and last_ok),
        "sasCompatibleAvailable": True,
        "sasCompatibleSupportedProcs": SUPPORTED_PROCS,
        "connectionMethod": "SASPy configured session" if execution_mode == "saspy_config" else ("External SAS export" if execution_mode == "external_export" else "Template only"),
        "sasExecutionMode": execution_mode,
        "lastConnectionTest": str(settings.get("lastConnectionTestedAt") or ""),
        "lastError": sanitize_error(last_error),
        "setupGuidance": sas_setup_guidance(saspy_installed, execution_mode, config_found, last_ok),
        "settings": public_sas_settings(settings),
    }


def ensure_sas_config_files() -> None:
    SAS_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not SAS_CONFIG_EXAMPLE_PATH.exists():
        SAS_CONFIG_EXAMPLE_PATH.write_text(
            json.dumps(
                {
                    "cfgname": "winlocal",
                    "cfgfile": "C:/Users/james/path/to/sascfg_personal.py",
                    "executionMode": "saspy_config",
                    "updatedAt": "",
                    "updatedBy": "",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    if not SAS_CONFIG_PATH.exists():
        SAS_CONFIG_PATH.write_text(
            json.dumps(
                {
                    "cfgname": "",
                    "cfgfile": "",
                    "executionMode": "template_only",
                    "updatedAt": "",
                    "updatedBy": "",
                    "lastConnectionOk": False,
                    "lastConnectionTestedAt": "",
                    "lastConnectionError": "",
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def load_sas_runtime_settings() -> Dict[str, Any]:
    ensure_sas_config_files()
    try:
        payload = json.loads(SAS_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}
    mode = payload.get("executionMode") if payload.get("executionMode") in {"template_only", "saspy_config", "external_export"} else "template_only"
    return {
        "cfgname": str(payload.get("cfgname") or ""),
        "cfgfile": str(payload.get("cfgfile") or ""),
        "executionMode": mode,
        "updatedAt": str(payload.get("updatedAt") or ""),
        "updatedBy": str(payload.get("updatedBy") or ""),
        "lastConnectionOk": bool(payload.get("lastConnectionOk")),
        "lastConnectionTestedAt": str(payload.get("lastConnectionTestedAt") or ""),
        "lastConnectionError": str(payload.get("lastConnectionError") or ""),
    }


def write_sas_runtime_settings(settings: Dict[str, Any]) -> None:
    ensure_sas_config_files()
    safe = {
        "cfgname": str(settings.get("cfgname") or ""),
        "cfgfile": str(settings.get("cfgfile") or ""),
        "executionMode": settings.get("executionMode") if settings.get("executionMode") in {"template_only", "saspy_config", "external_export"} else "template_only",
        "updatedAt": str(settings.get("updatedAt") or now_iso()),
        "updatedBy": str(settings.get("updatedBy") or "local_user"),
        "lastConnectionOk": bool(settings.get("lastConnectionOk")),
        "lastConnectionTestedAt": str(settings.get("lastConnectionTestedAt") or ""),
        "lastConnectionError": sanitize_error(str(settings.get("lastConnectionError") or "")),
    }
    SAS_CONFIG_PATH.write_text(json.dumps(safe, indent=2), encoding="utf-8")


def public_sas_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "cfgname": settings.get("cfgname", ""),
        "cfgfile": settings.get("cfgfile", ""),
        "executionMode": settings.get("executionMode", "template_only"),
        "updatedAt": settings.get("updatedAt", ""),
        "updatedBy": settings.get("updatedBy", ""),
        "lastConnectionOk": bool(settings.get("lastConnectionOk")),
        "lastConnectionTestedAt": settings.get("lastConnectionTestedAt", ""),
        "lastConnectionError": sanitize_error(str(settings.get("lastConnectionError") or "")),
    }


def detect_sas_config_files() -> list[str]:
    candidates: list[Path] = []
    for env_value in [os.getenv("ATLAS_SAS_CFGFILE"), os.getenv("SASPY_CONFIG_PATH")]:
        if env_value:
            candidates.append(Path(env_value).expanduser())
    for base in [Path.cwd(), Path.home(), SAS_CONFIG_DIR]:
        candidates.extend([base / "sascfg_personal.py", base / "sascfg.py"])
    try:
        spec = importlib.util.find_spec("saspy")
        if spec and spec.origin:
            package_dir = Path(spec.origin).parent
            candidates.extend([package_dir / "sascfg_personal.py", package_dir / "sascfg.py"])
    except Exception:
        pass
    found: list[str] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if resolved.exists() and str(resolved) not in found:
                found.append(str(resolved))
        except Exception:
            continue
    return found


def detect_sas_config_names(config_files: list[str]) -> list[str]:
    names: set[str] = set()
    for file_name in config_files:
        try:
            text = Path(file_name).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for match in re.finditer(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{", text, re.MULTILINE):
            if not match.group(1).startswith("__"):
                names.add(match.group(1))
    for env_name in [os.getenv("ATLAS_SAS_CFGNAME"), os.getenv("SAS_CONFIG_NAME")]:
        if env_name:
            names.add(env_name)
    return sorted(names)


def start_sas_session(settings: Dict[str, Any]):
    import saspy  # type: ignore

    cfgname = os.getenv("ATLAS_SAS_CFGNAME") or os.getenv("SAS_CONFIG_NAME") or str(settings.get("cfgname") or "")
    cfgfile = os.getenv("ATLAS_SAS_CFGFILE") or os.getenv("SASPY_CONFIG_PATH") or str(settings.get("cfgfile") or "")
    kwargs: Dict[str, Any] = {}
    if cfgname:
        kwargs["cfgname"] = cfgname
    if cfgfile:
        kwargs["cfgfile"] = cfgfile
    return saspy.SASsession(**kwargs)


def sas_setup_guidance(saspy_installed: bool, execution_mode: str, config_found: bool, last_ok: bool) -> list[str]:
    guidance = [
        "Local SAS: provide a SASPy cfgname/cfgfile that can start a local licensed SAS session.",
        "Remote SAS server: configure SASPy for the remote server outside ATLAS. Do not store passwords in ATLAS.",
        "SAS Studio / Viya: configure SASPy for the Viya environment and test the session before running SAS code.",
        "Export only: keep Template only or External SAS export mode and run the generated SAS program in your external SAS environment.",
    ]
    if not saspy_installed:
        return ["Install SASPy in the ATLAS Python environment before enabling managed SAS execution.", *guidance]
    if execution_mode != "saspy_config":
        return ["Select SASPy configured session to let ATLAS test a real SAS connection. Template-only mode validates code but does not run SAS.", *guidance]
    if not config_found:
        return ["SASPy is installed, but ATLAS did not find a cfgname or cfgfile. Enter a SASPy cfgname/cfgfile and run Test SAS Connection.", *guidance]
    if not last_ok:
        return ["Run Test SAS Connection. ATLAS will only enable Run SAS after a real SAS session starts successfully.", *guidance]
    return ["SAS connection test succeeded. ATLAS can run SAS through SASPy against a WORK preview table.", *guidance]


def sanitize_error(value: str) -> str:
    if not value:
        return ""
    redacted = re.sub(r"(?i)(password|passwd|pwd|token|secret)\s*[=:]\s*\S+", r"\1=<redacted>", value)
    return redacted[:4000]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def safe_sas_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value).strip("_").lower()
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"atlas_{cleaned}"
    return cleaned[:32]


def deterministic_question_cleanup(question: str, target: str) -> str:
    trimmed = re.sub(r"\s+", " ", question.strip())
    cleaned = re.sub(r"[?.!]+$", "", trimmed)
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    if re.match(r"(?i)^(which|what|how|why|does|do|is|are|can|should)\b", cleaned):
        return f"{cleaned}?"
    return f"Which factors in the selected dataset are most strongly associated with {target}, and what evidence supports that relationship?"
