# Governed code sandbox configuration

The Multi-Language Code Workspace only executes Python when an **approved**
sandbox is configured. Execution is off by default; nothing is enabled silently.

## Enable for local development

Set one environment variable before starting the API:

```
ATLAS_CODE_SANDBOX_COMMAND=default
```

`default` resolves to the project virtual environment interpreter
(`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` elsewhere) invoked in
isolated mode. This is the same interpreter that already runs the API, so
enabling execution does not widen the deployment's trust boundary.

PowerShell:

```powershell
$env:ATLAS_CODE_SANDBOX_COMMAND = "default"
.\.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8001
```

## Explicit command form

An operator may instead supply the full argument template. It must include
`{script}` and its executable must be on the approved allowlist:

```
ATLAS_CODE_SANDBOX_COMMAND="C:\path\to\.venv\Scripts\python.exe" -I {script}
```

Available placeholders: `{script}`, `{script_name}`, `{workdir}`.

## Approving another interpreter

Only the project virtual environment is approved by default. To approve a
container wrapper or another isolated interpreter, list absolute paths
(os.pathsep-separated):

```
ATLAS_CODE_SANDBOX_ALLOWLIST=C:\tools\atlas-sandbox\python.exe
```

## Enforced controls

| Control | Behavior |
| --- | --- |
| Approved executable | Resolved path must match the allowlist exactly; PATH shadowing and symlink substitution are rejected |
| No shell | Argument-vector invocation only; `;` `&` `\|` `>` `<` `` ` `` `$` and newlines are rejected |
| Script binding | The template must reference `{script}`, so it cannot run something other than the submitted code |
| Timeout | `ATLAS_PYTHON_RUN_TIMEOUT_SECONDS` (default 60s); the process is terminated on expiry |
| Output bounds | stdout/stderr capped at `ATLAS_PYTHON_RUN_MAX_OUTPUT_CHARS` (default 200,000) with a truncation flag |
| Code size | `ATLAS_PYTHON_RUN_MAX_CHARS` (default 120,000) |
| Isolated workdir | Fresh per-run directory under `ATLAS_PYTHON_RUNTIME_DIR`, removed afterwards |
| Environment allowlist | Only `SAFE_ENV_KEYS` are inherited; no other secrets reach the child |
| Dataset access | The authorized artifact is resolved server-side and copied into the run's own workdir; user code never receives a server path |
| Authorization | `/python/run` requires an authenticated user and, when a projectId is supplied, `authorize_modeling_scope(..., "view")` |

## Disabling

`ATLAS_HOSTED_MODE=1` or `ATLAS_ENABLE_PYTHON_RUN=0` reports the `disabled`
capability state, and the UI disables Run Python with an explanation.
