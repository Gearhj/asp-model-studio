# Operator runbook

Build from a clean reviewed commit:

```powershell
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts\build_nfl_personnel_capture_deployment.py --source-root C:\Users\james\asp-model-studio-source-nfl-personnel-capture
```

Inspect the no-network owner plan:

```powershell
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts\run_nfl_personnel_prospective_capture.py
```

Inspect installation without changing Task Scheduler:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_nfl_personnel_capture.ps1 -Mode Plan -DeploymentRoot <immutable-deployment-path>
```

Installation requires the owner's explicit authorization and an elevated shell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_nfl_personnel_capture.ps1 -Mode Install -DeploymentRoot <immutable-deployment-path>
```

Status:

```powershell
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts\status_nfl_personnel_capture.py
```

Stop conditions are deployment/member hash mismatch, missing rights acknowledgement, a second owner marker, overlap lock, daily request exhaustion, per-capture byte exhaustion, storage exhaustion, schema with no admitted fields, missing/ambiguous local schedule, or evidence that cannot be bound before its horizon cutoff. Provider failure remains isolated from every forecast publisher. Quarantine a bad object by retaining it and preventing its projection; do not delete or rewrite its receipt.

Rollback removes this task and its runtime binding only. It does not delete raw evidence and never changes a model, forecast, AISP, exchange, or other scheduled task.
