# ATLAS Private Demo Setup

Use synthetic or non-sensitive data only. This local demo is not approved for customer, account, personal, confidential, or regulated production data.

## Start the Backend

Run from the repository root because `server.main` uses package-relative imports:

```powershell
Set-Location "C:\Users\james\ds-workflow-starter"
$env:ATLAS_LOCAL_DEV = "true"
$env:ATLAS_DEV_MODE = "true"
$env:ATLAS_HOSTED_MODE = "false"
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

Do not run `uvicorn main:app` from inside `server`.

## Start the Frontend

In another PowerShell window:

```powershell
Set-Location "C:\Users\james\ds-workflow-starter"
npm run dev
```

Open `http://127.0.0.1:5174`.

## Check Ports and Process Identity

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue

$backend = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($backend) { Get-CimInstance Win32_Process -Filter "ProcessId=$($backend.OwningProcess)" | Select-Object ProcessId, Name, CommandLine }
```

Stop only a process you have identified:

```powershell
Stop-Process -Id ACTUAL_PROCESS_ID -Force
```

## Verify the Backend and User Context

```powershell
$base = "http://127.0.0.1:8000/api"
$headers = @{
  "X-ATLAS-USER-ID" = "user_eecc3a44ed694307"
}

Invoke-RestMethod -Uri "$base/persistence/health" -Method GET
Invoke-RestMethod -Uri "$base/persistence/health" -Headers $headers -Method GET
Invoke-RestMethod -Uri "$base/projects" -Headers $headers -Method GET
```

The health response should identify `atlas-backend` and `sqlite-persistence`. The user header is accepted only in non-hosted local/development mode and only for an active user in the local security database.

## Inspect SQLite

```powershell
python scripts/inspect_atlas_db.py
python scripts/inspect_atlas_db.py --limit 20
```

The inspector reports the database path, table counts, users, projects, workflow states, evidence, runs, documentation, exports, decisions, audit events, and tester feedback.

## Reset a Disposable Demo Database

The reset utility never runs automatically. It refuses to act without `--yes` and creates a timestamped backup by default:

```powershell
python scripts/reset_atlas_demo_db.py --db ".tmp\disposable_atlas_demo.db" --yes
```

Do not reset `server\data\atlas_local.db` unless the current data has been reviewed and the reset is intentional.

## Verify Backend Recovery After Clearing Browser Storage

1. Confirm the project is visible in **Open Project** with source **ATLAS database**.
2. Open browser developer tools for `127.0.0.1:5174`.
3. In **Application > Storage**, clear site data for the local frontend origin.
4. Reload ATLAS and sign in or use the seeded local admin.
5. Open **Open Project**, choose the database-backed project, and verify workflow state, evidence, runs, documentation, exports, and decisions.

Clearing browser storage removes compatibility snapshots. It does not delete SQLite records.

## Optional Remote Demo Tunnel

Expose the frontend only after confirming local operation, access controls, and data safety. If Cloudflare Tunnel or ngrok is used later, keep the backend bound to localhost, use the existing frontend proxy, protect the tunnel, and continue using synthetic or non-sensitive data only. Hosted identity and production security controls are not enabled by a tunnel.
