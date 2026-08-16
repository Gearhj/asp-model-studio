[CmdletBinding()]
param(
    [switch]$Start
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$financialAtlasRoot = [IO.Path]::GetFullPath("C:\Users\james\ds-workflow-starter")
$repoFull = [IO.Path]::GetFullPath($repoRoot)

if ($repoFull.Equals($financialAtlasRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to configure ASP Model Studio from the financial ATLAS source repository."
}

$gitDirectory = Join-Path $repoRoot ".git"
if (-not (Test-Path -LiteralPath $gitDirectory -PathType Container)) {
    throw "ASP Model Studio requires an independent .git directory."
}

$alternates = Join-Path $gitDirectory "objects\info\alternates"
if ((Test-Path -LiteralPath $alternates) -and (Get-Item -LiteralPath $alternates).Length -gt 0) {
    throw "Refusing to run with a shared Git object-store alternate."
}

$runtimeRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot ".runtime\asp-model-studio"))
$repoPrefix = $repoFull.TrimEnd('\') + '\'
if (-not $runtimeRoot.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Runtime root escaped the ASP Model Studio repository."
}

$frontendPort = if ($env:ASP_MODEL_STUDIO_FRONTEND_PORT) { [int]$env:ASP_MODEL_STUDIO_FRONTEND_PORT } else { 5274 }
$backendPort = if ($env:ASP_MODEL_STUDIO_BACKEND_PORT) { [int]$env:ASP_MODEL_STUDIO_BACKEND_PORT } else { 8101 }
$previewPort = if ($env:ASP_MODEL_STUDIO_PREVIEW_PORT) { [int]$env:ASP_MODEL_STUDIO_PREVIEW_PORT } else { 4274 }
if ($frontendPort -eq $backendPort -or $frontendPort -in @(5174, 8001) -or $backendPort -in @(5174, 8001)) {
    throw "ASP Model Studio ports must be distinct and must not use ATLAS ports 5174 or 8001."
}
if ($previewPort -in @($frontendPort, $backendPort, 4174, 5174, 8001)) {
    throw "ASP Model Studio preview port must be distinct and must not use inherited ATLAS ports."
}

$paths = [ordered]@{
    persistence = Join-Path $runtimeRoot "persistence"
    security = Join-Path $runtimeRoot "security"
    datasets = Join-Path $runtimeRoot "artifacts\datasets"
    datasetBackups = Join-Path $runtimeRoot "backups\datasets"
    checkpoints = Join-Path $runtimeRoot "checkpoints"
    evidence = Join-Path $runtimeRoot "artifacts\evidence"
    featureManifests = Join-Path $runtimeRoot "artifacts\feature-manifests"
    modelRegistry = Join-Path $runtimeRoot "artifacts\model-registry"
    scoringRuns = Join-Path $runtimeRoot "artifacts\scoring-runs"
    vifPlans = Join-Path $runtimeRoot "artifacts\vif-plans"
    restrictedMetadata = Join-Path $runtimeRoot "restricted-metadata"
    bureauCatalogs = Join-Path $runtimeRoot "bureau-catalogs"
    results = Join-Path $runtimeRoot "results"
    uploads = Join-Path $runtimeRoot "uploads"
    logs = Join-Path $runtimeRoot "logs"
    cache = Join-Path $runtimeRoot "cache"
    temp = Join-Path $runtimeRoot "temp"
    pythonRuntime = Join-Path $runtimeRoot "python-runtime"
    sasConfig = Join-Path $runtimeRoot "sas-config"
}

foreach ($path in $paths.Values) {
    [IO.Directory]::CreateDirectory($path) | Out-Null
}

$sessionSecret = $env:ASP_MODEL_STUDIO_SESSION_SECRET
if (-not $sessionSecret) {
    $secretBytes = New-Object byte[] 32
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($secretBytes)
    }
    finally {
        $random.Dispose()
    }
    $sessionSecret = [Convert]::ToBase64String($secretBytes)
}

$environment = [ordered]@{
    ATLAS_APPLICATION_NAME = "ASP Model Studio API"
    ATLAS_INSTANCE_ID = "asp-model-studio-local"
    ATLAS_WORKER_ID = "asp-model-studio-local-worker"
    ATLAS_SESSION_COOKIE_NAME = "asp_model_studio_session"
    ATLAS_SESSION_SECRET = $sessionSecret
    ATLAS_AUTH_ENABLED = "true"
    ATLAS_HOSTED_MODE = "false"
    ATLAS_LOCAL_DEV = "false"
    ATLAS_ENABLE_DEV_USER_HEADER = "false"
    ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP = "false"
    ATLAS_ALLOW_PUBLIC_REGISTRATION = "false"
    ATLAS_COOKIE_SECURE = "false"
    ATLAS_CORS_ORIGINS = "http://127.0.0.1:$frontendPort,http://localhost:$frontendPort"
    ATLAS_SQLITE_PATH = Join-Path $paths.persistence "asp_model_studio.db"
    ATLAS_SECURITY_ROOT = $paths.security
    ATLAS_SECURITY_DB_PATH = Join-Path $paths.security "asp_model_studio_security.db"
    ATLAS_DATASET_LIBRARY_ROOT = $paths.datasets
    ATLAS_DATASET_LIBRARY_BACKUP_ROOT = $paths.datasetBackups
    ATLAS_CHECKPOINT_PATH = Join-Path $paths.checkpoints "asp_model_studio_session.json"
    ATLAS_EVIDENCE_ROOT = $paths.evidence
    ATLAS_FEATURE_MANIFEST_ROOT = $paths.featureManifests
    ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT = $paths.modelRegistry
    ATLAS_SCORING_RUN_ARTIFACT_ROOT = $paths.scoringRuns
    ATLAS_VIF_PLAN_ROOT = $paths.vifPlans
    ATLAS_PYTHON_RUNTIME_DIR = $paths.pythonRuntime
    ATLAS_SAS_CONFIG_DIR = $paths.sasConfig
    ATLAS_RESTRICTED_METADATA_ROOT = $paths.restrictedMetadata
    ATLAS_BUREAU_CATALOG_REGISTRY_ROOT = $paths.bureauCatalogs
    ASP_MODEL_STUDIO_RESULTS_ROOT = $paths.results
    ASP_MODEL_STUDIO_UPLOAD_ROOT = $paths.uploads
    ASP_MODEL_STUDIO_LOG_ROOT = $paths.logs
    ASP_MODEL_STUDIO_CACHE_ROOT = $paths.cache
    ASP_MODEL_STUDIO_TEMP_ROOT = $paths.temp
    ASP_MODEL_STUDIO_FRONTEND_PORT = [string]$frontendPort
    ASP_MODEL_STUDIO_BACKEND_PORT = [string]$backendPort
    ASP_MODEL_STUDIO_PREVIEW_PORT = [string]$previewPort
    ASP_MODEL_STUDIO_API_BASE = "http://127.0.0.1:$backendPort/api"
    VITE_APP_TARGET = "modeling"
    VITE_API_BASE = "http://127.0.0.1:$backendPort/api"
    VITE_API_PROXY_TARGET = "http://127.0.0.1:$backendPort"
    TEMP = $paths.temp
    TMP = $paths.temp
    PYTHONDONTWRITEBYTECODE = "1"
    PYTHONPYCACHEPREFIX = Join-Path $paths.cache "python"
    NODE_COMPILE_CACHE = Join-Path $paths.cache "node"
    MPLCONFIGDIR = Join-Path $paths.cache "matplotlib"
    NUMBA_CACHE_DIR = Join-Path $paths.cache "numba"
    JOBLIB_TEMP_FOLDER = Join-Path $paths.temp "joblib"
    COMPOSE_PROJECT_NAME = "asp-model-studio"
}

foreach ($entry in $environment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, [string]$entry.Value, "Process")
}

function Assert-PortAvailable([int]$Port) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        throw "Port $Port is already in use; no process was started."
    }
}

Assert-PortAvailable $frontendPort
Assert-PortAvailable $backendPort

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
$pythonReady = $false
if (Test-Path -LiteralPath $python -PathType Leaf) {
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $null = & $python -c "import fastapi, pydantic, pandas, sklearn; from server.main import app" 2>$null
        $pythonReady = $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

$nodeReady = (
    (Test-Path -LiteralPath (Join-Path $repoRoot "node_modules") -PathType Container) -and
    (Test-Path -LiteralPath (Join-Path $repoRoot "node_modules\vite\package.json") -PathType Leaf)
)

$validation = [ordered]@{
    repository = $repoRoot
    runtimeRoot = $runtimeRoot
    applicationName = $environment.ATLAS_APPLICATION_NAME
    instanceId = $environment.ATLAS_INSTANCE_ID
    cookieName = $environment.ATLAS_SESSION_COOKIE_NAME
    frontendPort = $frontendPort
    backendPort = $backendPort
    previewPort = $previewPort
    pythonReady = $pythonReady
    nodeReady = $nodeReady
    remotes = @(git -C $repoRoot remote -v)
    launchRequested = [bool]$Start
}

if (-not $Start) {
    $validation | ConvertTo-Json -Depth 4
    return
}

if (-not $validation.pythonReady -or -not $validation.nodeReady -or -not $npm) {
    throw "Target-local Python and Node dependencies must be rebuilt before launch."
}

$backendOut = Join-Path $paths.logs "backend.stdout.log"
$backendErr = Join-Path $paths.logs "backend.stderr.log"
$frontendOut = Join-Path $paths.logs "frontend.stdout.log"
$frontendErr = Join-Path $paths.logs "frontend.stderr.log"

# Codex and a few Windows launch hosts can supply both `PATH` and `Path` in the
# inherited process block. Windows PowerShell's Start-Process rejects that
# otherwise valid environment as a duplicate-key dictionary. Normalize the
# case once, preserving the resolved value, before creating either child.
$normalizedProcessPath = [Environment]::GetEnvironmentVariable("Path", "Process")
if ($normalizedProcessPath) {
    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $normalizedProcessPath, "Process")
}

$backend = Start-Process -FilePath $python -ArgumentList @(
    "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", [string]$backendPort, "--workers", "1"
) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -PassThru

$frontend = Start-Process -FilePath $npm -ArgumentList @(
    "run", "dev", "--", "--host", "127.0.0.1", "--port", [string]$frontendPort, "--strictPort"
) -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -PassThru

[ordered]@{
    started = $true
    backendProcessId = $backend.Id
    frontendProcessId = $frontend.Id
    backendUrl = "http://127.0.0.1:$backendPort/api/health"
    frontendUrl = "http://127.0.0.1:$frontendPort"
    logRoot = $paths.logs
} | ConvertTo-Json -Depth 4
