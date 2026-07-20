# ATLAS SQLite Persistence

ATLAS uses SQLite as its local server-backed application store while retaining the existing browser persistence layer as a compatibility fallback. SQLite is the authoritative backend store when the API is available; browser storage keeps existing projects usable when it is not.

## Database Location

The default database is:

```text
server/data/atlas_local.db
```

Set `ATLAS_SQLITE_PATH` before starting the backend to use another path:

```powershell
$env:ATLAS_SQLITE_PATH = "C:\atlas-data\atlas_local.db"
```

The backend creates the parent directory and database on startup, applies only migrations that have not already run, and never drops existing tables or records. The application database is separate from `server/artifacts/security/atlas_security.db`, which remains the authentication and security store.

## Tables

- `schema_migrations`: applied migration ledger.
- `users`: application-facing user references and ownership metadata.
- `projects`: project identity, workflow, status, ownership, and flexible metadata.
- `workflow_state`: current step, completed steps, workflow status, and evidence status.
- `datasets`: project dataset registrations.
- `dataset_versions`: immutable dataset version, shape, hash, profile, and schema metadata.
- `evidence_artifacts`: governed workflow evidence and approval state.
- `run_records`: model, analysis, or workflow execution parameters and results.
- `decision_journal`: project decisions and review state.
- `documentation_packages`: generated documentation package state and payloads.
- `export_artifacts`: export manifests, locations, hashes, and metadata.

Flexible prototype payloads use centrally serialized JSON in `TEXT` columns. Date/time values are stored as UTC ISO-8601 text.

## API

The persistence health endpoint is public so local diagnostics still work when authentication is unavailable:

```text
GET /api/persistence/health
```

Authenticated persistence routes:

```text
GET  /api/projects
POST /api/projects
GET  /api/projects/{project_id}
PUT  /api/projects/{project_id}

GET /api/projects/{project_id}/workflow-state
PUT /api/projects/{project_id}/workflow-state

GET  /api/projects/{project_id}/evidence
POST /api/projects/{project_id}/evidence
PUT  /api/projects/{project_id}/evidence/{evidence_id}

GET  /api/projects/{project_id}/runs
POST /api/projects/{project_id}/runs

GET  /api/projects/{project_id}/decisions
POST /api/projects/{project_id}/decisions

GET  /api/projects/{project_id}/documentation
POST /api/projects/{project_id}/documentation

GET  /api/projects/{project_id}/exports
POST /api/projects/{project_id}/exports
```

### Local development user context

Start the backend from the repository root so Python loads `server.main` as a package:

```powershell
Set-Location "C:\Users\james\ds-workflow-starter"
$env:ATLAS_LOCAL_DEV = "true"
$env:ATLAS_DEV_MODE = "true"
$env:ATLAS_HOSTED_MODE = "false"
.\.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

Protected routes require either an authenticated ATLAS session or a selected user. In non-hosted local/development mode, provide the development-only header with the existing seeded admin:

```powershell
$headers = @{ "X-ATLAS-USER-ID" = "user_eecc3a44ed694307" }
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/projects" -Headers $headers
```

`local-dev-user` is also accepted as an optional alias. When no dedicated alias account exists, ATLAS resolves it to the seeded local admin before creating another account. The header is ignored in hosted mode. A request without a session or header returns a diagnostic hint and the active development users instead of the former context-free `no user selected` response. See `ATLAS_BACKEND_PERSISTENCE_TEST_PLAN.md` for complete PowerShell CRUD examples.

## Inspect the Database

Check backend health:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/persistence/health
```

Persistence health is public and does not require a selected user. The response includes `requiresUserContext` and `devUserHeaderEnabled` diagnostics.

With the SQLite command-line client, use the full path so the result does not depend on the current directory:

```powershell
sqlite3 "C:\Users\james\ds-workflow-starter\server\data\atlas_local.db" ".tables"
sqlite3 -header -column "C:\Users\james\ds-workflow-starter\server\data\atlas_local.db" "SELECT project_id, project_name, template_id, workflow_type, updated_at FROM projects ORDER BY updated_at DESC;"
```

The read-only repository inspector reports every governed table plus the latest records:

```powershell
python scripts/inspect_atlas_db.py
.\.venv\Scripts\python.exe scripts\inspect_atlas_db.py --limit 20
```

With the repository Python environment:

```powershell
@'
import sqlite3

connection = sqlite3.connect("server/data/atlas_local.db")
connection.row_factory = sqlite3.Row
for row in connection.execute("SELECT project_id, project_name, workflow_type, updated_at FROM projects ORDER BY updated_at DESC"):
    print(dict(row))
connection.close()
'@ | .\.venv\Scripts\python.exe -
```

## Save Status

The project header reports the active persistence outcome:

- `Local only`: the browser compatibility copy exists and database synchronization is pending.
- `Saved to ATLAS database`: both the local copy and SQLite write completed.
- `Backend unavailable`: the server could not be reached; the local copy remains available.
- `Save failed`: the server rejected or could not persist the database record; the local copy remains available.

Project/workflow writes are queued briefly to combine rapid state changes. Evidence, documentation, decisions, and export manifests are mirrored when they are created or updated.

## Backup

For a consistent offline backup, stop the backend first. Then use either SQLite's backup command:

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
sqlite3 server/data/atlas_local.db ".backup 'backups/atlas_local.db'"
```

or Python's online backup API:

```powershell
@'
import sqlite3

source = sqlite3.connect("server/data/atlas_local.db")
target = sqlite3.connect("backups/atlas_local.db")
source.backup(target)
target.close()
source.close()
'@ | .\.venv\Scripts\python.exe -
```

Do not back up by copying only the `.db` file while the backend is actively writing in WAL mode.

## Reset Local Demo Data

Resetting SQLite does not clear browser-local projects. Stop the backend, verify that the path is the intended ATLAS demo database, and remove the database plus its WAL sidecars:

```powershell
$database = Resolve-Path server/data/atlas_local.db -ErrorAction SilentlyContinue
if ($database) {
  Remove-Item -LiteralPath $database -Force
  Remove-Item -LiteralPath "$database-wal" -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath "$database-shm" -Force -ErrorAction SilentlyContinue
}
```

Restart the backend. ATLAS recreates the schema and reapplies all migrations. Existing browser projects remain available and will be mirrored again on their next save.

## Migrations

`server/persistence/schema.sql` bootstraps the migration ledger. Ordered SQL files in `server/persistence/migrations/` contain additive schema changes. Startup records each applied filename in `schema_migrations`, so a migration runs once. Do not edit a migration that may already have shipped; add the next numbered migration instead.

## Future SQL Server Migration

The service and repository interfaces isolate persistence calls from route and UI code. A SQL Server implementation can preserve those interfaces while replacing the SQLite connection and SQL dialect. A production migration should:

1. Add a SQL Server connection provider and transaction adapter.
2. Port repository statements to parameterized T-SQL or a shared query builder.
3. Move migrations to a production migration tool with environment-specific credentials and rollback policy.
4. Retain JSON payloads as `NVARCHAR(MAX)` initially, then adopt SQL Server JSON constraints or normalized tables where query patterns justify it.
5. Convert ISO timestamp text to `datetime2`/`datetimeoffset` and define production retention, backup, encryption, and access-control policies.
6. Backfill SQLite records through repository-level export/import so API consumers do not change.

Full SQL Server support is intentionally outside this first implementation.
