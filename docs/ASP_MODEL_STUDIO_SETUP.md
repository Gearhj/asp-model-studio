# ASP Model Studio Local Setup

## Classification and purpose

Repository: `C:\Users\james\asp-model-studio`

ASP Model Studio is an independent, local/private model-development platform forked from financial-services ATLAS. This baseline exists so a later phase can assess sports-domain architecture and rebranding without changing financial ATLAS.

It is not approved for public hosting, live model serving, ASP integration, sports data access, model training, deployment, forecasts, or positions. Those activities are outside this fork phase.

## Inherited limitations

The application retains the ATLAS financial-services workflows and their known security, authorization, artifact-governance, and hosted-readiness limitations. A separate assessment is required before sports functionality or public hosting.

Some inherited stores use repository-relative paths rather than environment overrides. Because ASP Model Studio has its own source directory, those paths remain target-local and cannot resolve into financial ATLAS when commands are run from this repository. Do not run target commands from the financial ATLAS directory.

The local launcher adds a unique session-cookie name and application instance identity, pins all configurable durable authorities beneath `.runtime/asp-model-studio`, reserves distinct ports, and refuses to run from the financial ATLAS root. It does not create users, disable authentication, or expose the application publicly.

## Dependency rebuild

Use only the target repository:

```powershell
Set-Location C:\Users\james\asp-model-studio
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
npm ci
```

Do not copy `.venv`, `node_modules`, `.env`, databases, artifacts, caches, or build output from financial ATLAS. Do not upgrade package versions during baseline reconstruction.

The npm dependency graph is locked by `package-lock.json`. Python requirements are pinned but are not a fully hashed lock, and the root and server requirement files conflict for several framework/data packages. The root `requirements.txt` cannot currently resolve because it pins `pyarrow==25.0.0` while `mlflow==2.17.0` requires PyArrow below 18. The baseline therefore uses the focused `server/requirements.txt` environment used by the repository CI, without changing any versions. This is sufficient for the verified core application checks but is not a reproducible full-platform Python lock. Resolve the packaging authority in a future architecture phase.

## Safe configuration validation

The launcher is validation-only unless `-Start` is explicitly supplied:

```powershell
.\scripts\start-asp-model-studio.ps1
```

It checks the independent Git boundary, refuses Git alternates, creates only target-local ignored runtime directories, configures isolated authorities, and verifies that ports `5274` and `8101` are unused. It prints no session secret.

## Optional local start after verification

Only after dependencies and target tests succeed:

```powershell
.\scripts\start-asp-model-studio.ps1 -Start
```

This starts one hidden backend worker on `127.0.0.1:8101` and Vite on `127.0.0.1:5274`, with logs under `.runtime/asp-model-studio/logs`. The target uses the `asp_model_studio_session` cookie and the `ASP Model Studio API` application title. The validation output reports instance `asp-model-studio-local`; the unauthenticated `/api/health` response deliberately remains minimal.

Never invoke `npm run sync:atlas` from ASP Model Studio. Never point any target variable at `C:\Users\james\ds-workflow-starter` or `C:\Users\james\ai-sports-predictor`.

Direct Vite development defaults are target-specific: frontend `5274`, preview `4274`, and API proxy `8101`. The inherited `sync:atlas` command is retained only as a fail-closed compatibility entry and always throws before any copy operation. E2E seed helpers resolve fixture files from this repository and default to the target backend; they do not resolve financial ATLAS paths.

## Runtime authority map

The launcher isolates:

- persistence and security databases;
- dataset library and backups;
- evidence, feature manifests, model registry, scoring results, and VIF plans;
- checkpoints, results, uploads, logs, caches, Python execution, SAS configuration, and temporary workspaces;
- frontend/backend ports, session cookie, application/instance identity, worker identifier, and Compose project name.

The results, upload, log, cache, and worker variables are reserved target contracts where inherited code does not yet consume a central authority. Repository-relative inherited stores remain isolated by the independent target directory.

## Next permissible phase

The next phase is an independent **ASP Model Studio sports-domain architecture and rebranding assessment**. Do not begin it as part of baseline fork maintenance.
