# ATLAS Backend Persistence Test Plan

Run every command in this plan from the repository root:

`C:\Users\james\ds-workflow-starter`

Do not change into `server` and run `uvicorn main:app`. `server/main.py` is a package module and intentionally uses relative imports.

## Start the Backend from the Repository Root

In a dedicated PowerShell window:

```powershell
Set-Location "C:\Users\james\ds-workflow-starter"
$env:ATLAS_LOCAL_DEV = "true"
$env:ATLAS_DEV_MODE = "true"
$env:ATLAS_HOSTED_MODE = "false"
.\.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

The equivalent system-Python command is:

```powershell
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

Do not test against an existing listener until its identity is confirmed. Check port `8000` before startup:

```powershell
$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
$listener | Select-Object LocalAddress, LocalPort, OwningProcess
```

If another application already owns port `8000`, stop it only when it is safe to do so or choose a free port and update `$base`. A response from another service is not evidence that ATLAS authentication failed.

After ATLAS starts, verify the service fingerprint:

```powershell
$health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/persistence/health"
$health | Select-Object service, component, status, requiresUserContext, devUserHeaderEnabled
```

Expected values include `service = atlas-backend`, `component = sqlite-persistence`, and `requiresUserContext = false`. If this endpoint returns `{"error":"no user selected"}`, the request reached an old or different service because the current ATLAS persistence-health route is public. The backend root intentionally has no route; use `/api/health`, `/api/persistence/health`, or `/docs`.

## PowerShell API Testing with Local Dev User

The `X-ATLAS-USER-ID` override is accepted only in non-hosted local/development mode. Use the seeded ATLAS Local Admin for deterministic manual testing. `local-dev-user` remains an optional alias and is not required when the seeded admin exists. Hosted/production mode does not accept this override.

```powershell
$root = "C:\Users\james\ds-workflow-starter"
$database = Join-Path $root "server\data\atlas_local.db"
$base = "http://127.0.0.1:8000/api"
$seededAdminUserId = "user_eecc3a44ed694307"
$headers = @{ "X-ATLAS-USER-ID" = $seededAdminUserId }
$projectId = "persistence-api-test"
```

Optional alias:

```powershell
$localDevHeaders = @{ "X-ATLAS-USER-ID" = "local-dev-user" }
```

### 1. Persistence health

```powershell
Invoke-RestMethod -Uri "$base/persistence/health" -Method GET
Invoke-RestMethod -Uri "$base/persistence/health" -Headers $headers -Method GET
```

This endpoint is intentionally public and works both with and without the development header. Confirm that it reports `service = atlas-backend`, `requiresUserContext = false`, and `devUserHeaderEnabled = true`.

### 2. Confirm current development user

```powershell
Invoke-RestMethod -Uri "$base/auth/me" -Headers $headers -Method GET
Invoke-RestMethod -Uri "$base/projects" -Headers $headers -Method GET
```

Without the header or a valid session, protected persistence routes return `401` plus a local-testing hint and active development users:

```powershell
try { Invoke-RestMethod -Uri "$base/projects" -Method GET } catch { $_.ErrorDetails.Message }
```

### 3. Create or update a transportation project

```powershell
$projectBody = @{
  projectName = "Persistence API Transportation Test"
  projectType = "optimization"
  workflowType = "optimization"
  templateId = "transportation_logistics"
  status = "active"
  metadata = @{ source = "manual-api-test" }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "$base/projects/$projectId" -Headers $headers -Method PUT -ContentType "application/json" -Body $projectBody
Invoke-RestMethod -Uri "$base/projects/$projectId" -Headers $headers -Method GET
```

### 4. Save and reload workflow state

```powershell
$workflowBody = @{
  currentStepId = "optimization-14"
  completedSteps = 1..14 | ForEach-Object { "optimization-$_" }
  workflowStatus = @{ workflowId = "optimization"; status = "complete" }
  stepEvidenceStatus = @{ "optimization-14" = "approved" }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "$base/projects/$projectId/workflow-state" -Headers $headers -Method PUT -ContentType "application/json" -Body $workflowBody
Invoke-RestMethod -Uri "$base/projects/$projectId/workflow-state" -Headers $headers -Method GET
```

### 5. Save and reload evidence

```powershell
$evidenceBody = @{
  evidenceId = "ev-api-optimization-validation"
  workflowType = "optimization"
  stepId = "optimization-10"
  artifactType = "optimization_validation"
  status = "approved"
  title = "Optimization validation"
  summary = "API persistence verification artifact."
  sourceRef = "/workflow/optimization/10"
  artifactHash = "manual-api-test"
  payload = @{ validationScore = 100; gateStatus = "pass" }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "$base/projects/$projectId/evidence" -Headers $headers -Method POST -ContentType "application/json" -Body $evidenceBody
Invoke-RestMethod -Uri "$base/projects/$projectId/evidence" -Headers $headers -Method GET
```

### 6. Save and reload a run record

```powershell
$runBody = @{
  runId = "run-api-optimization-solver"
  runType = "optimization_solver"
  workflowType = "optimization"
  status = "complete"
  startedAt = (Get-Date).ToUniversalTime().ToString("o")
  completedAt = (Get-Date).ToUniversalTime().ToString("o")
  parameters = @{ solver = "highs" }
  metrics = @{ solver_status = "optimal"; business_validity = "valid"; total_cost = 123.45 }
  artifacts = @{ formulation_hash = "manual-api-test" }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "$base/projects/$projectId/runs" -Headers $headers -Method POST -ContentType "application/json" -Body $runBody
Invoke-RestMethod -Uri "$base/projects/$projectId/runs" -Headers $headers -Method GET
```

### 7. Save and reload an export manifest

Browser downloads do not have a server file path. They must explicitly declare client-only delivery rather than claiming that a server file exists.

```powershell
$exportBody = @{
  exportId = "export-api-governed-json"
  exportType = "governed_json"
  fileName = "optimization-study.json"
  filePath = $null
  storageMode = "client_generated"
  artifactHash = "manual-api-test"
  metadata = @{ delivery = "browser_download"; clientOnly = $true; fileExists = $false }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "$base/projects/$projectId/exports" -Headers $headers -Method POST -ContentType "application/json" -Body $exportBody
Invoke-RestMethod -Uri "$base/projects/$projectId/exports" -Headers $headers -Method GET
```

Expected persisted values include `storageMode = client_generated` and `filePath = not_applicable_client_download`.

### 8. Save documentation and a decision

```powershell
$documentationBody = @{
  packageId = "package-api-optimization-study"
  packageType = "optimization_study"
  status = "complete"
  readinessScore = 100
  sectionCount = 20
  completedSectionCount = 20
  payload = @{ executiveSummary = "Manual API verification" }
} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Uri "$base/projects/$projectId/documentation" -Headers $headers -Method POST -ContentType "application/json" -Body $documentationBody
Invoke-RestMethod -Uri "$base/projects/$projectId/documentation" -Headers $headers -Method GET

$decisionBody = @{
  decisionId = "decision-api-study-complete"
  decisionType = "optimization_study_completed"
  title = "Optimization study completed"
  summary = "Manual API persistence verification."
  status = "approved"
  owner = "Local Dev User"
  payload = @{ recommendation = "Recommended" }
} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Uri "$base/projects/$projectId/decisions" -Headers $headers -Method POST -ContentType "application/json" -Body $decisionBody
Invoke-RestMethod -Uri "$base/projects/$projectId/decisions" -Headers $headers -Method GET
```

### 9. Review audit events and submit tester feedback

```powershell
Invoke-RestMethod -Uri "$base/audit-log?projectId=$projectId" -Headers $headers -Method GET

$feedbackBody = @{
  projectId = $projectId
  route = "/workflow/optimization/10"
  workflowType = "optimization"
  stepId = "optimization-10"
  issueType = "usability"
  severity = "medium"
  expectedBehavior = "Validation status remains visible."
  actualBehavior = "The reviewer needed a clearer status."
  notes = "Manual private-demo API verification."
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "$base/demo-feedback" -Headers $headers -Method POST -ContentType "application/json" -Body $feedbackBody
Invoke-RestMethod -Uri "$base/demo-feedback?projectId=$projectId" -Headers $headers -Method GET
```

## Direct SQLite Verification

Use the full path so the command is independent of the current directory:

```powershell
sqlite3 "C:\Users\james\ds-workflow-starter\server\data\atlas_local.db" ".tables"
sqlite3 -header -column "C:\Users\james\ds-workflow-starter\server\data\atlas_local.db" "SELECT project_id, project_name, template_id FROM projects ORDER BY updated_at DESC;"
sqlite3 -header -column "C:\Users\james\ds-workflow-starter\server\data\atlas_local.db" "SELECT project_id, artifact_type, status FROM evidence_artifacts ORDER BY created_at DESC;"
sqlite3 -header -column "C:\Users\james\ds-workflow-starter\server\data\atlas_local.db" "SELECT project_id, run_type, status FROM run_records ORDER BY completed_at DESC;"
```

The repository inspector does not require the SQLite CLI:

```powershell
python scripts/inspect_atlas_db.py
# or
.\.venv\Scripts\python.exe scripts\inspect_atlas_db.py --limit 20
```

## Restart and Browser-Recovery Validation

1. Complete the Transportation / Logistics workflow actions in the UI, including normalization, solver, scenarios, sensitivity, validation, recommendation, implementation, documentation, and exports.
2. Run `python scripts/inspect_atlas_db.py` and verify nonzero rows in all governed artifact tables.
3. Restart the backend and frontend.
4. Clear browser local storage for `127.0.0.1:5174`.
5. Open **Open Project**, select the project labeled **ATLAS database**, and verify template, workflow progress, Overview, Evidence Center, documentation readiness, and results recover from SQLite.
