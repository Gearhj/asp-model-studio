[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$ManifestPath, [switch]$ScheduledInvocation, [switch]$RunNow)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$exitCode = 1
$failureCode = 'MANIFEST_READ_FAILED'
$manifest = $null
$manifestSha256 = $null
$failedRelativePath = $null
$codeValidated = $false
$processTreeGuarded = $false
$receiptRoot = Join-Path ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ManifestPath))) 'launcher-receipts'

function Write-LauncherReceipt([string]$Status, $Details) {
    # One immutable record per distinct outcome/context. Repeated STOP ticks,
    # healthy launches, or an unchanged error do not create a receipt every 5 min.
    $context = [ordered]@{
        status = $Status
        manifest_sha256 = $script:manifestSha256
        actual_owner_sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        session_id = [Diagnostics.Process]::GetCurrentProcess().SessionId
        powershell_version = $PSVersionTable.PSVersion.ToString()
        invocation = if ($ScheduledInvocation) { 'SCHEDULED_TASK_ACTION_REQUESTED' } else { 'MANUAL_LAUNCHER_VERIFICATION' }
        code_validated = $script:codeValidated
        process_tree_guarded = $script:processTreeGuarded
        details = $Details
    }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash($utf8.GetBytes(($context | ConvertTo-Json -Depth 8 -Compress)))
        $key = ([BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
    [IO.Directory]::CreateDirectory($script:receiptRoot) | Out-Null
    $path = Join-Path $script:receiptRoot ($key + '.json')
    if (Test-Path -LiteralPath $path) { return }
    $record = [ordered]@{
        schema_version = 1
        at_utc = [DateTime]::UtcNow.ToString('o')
        process_id = $PID
        context = $context
    }
    $bytes = $utf8.GetBytes(($record | ConvertTo-Json -Depth 8))
    try {
        $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
        try { $stream.Write($bytes, 0, $bytes.Length) }
        finally { $stream.Dispose() }
    }
    catch [IO.IOException] {
        if (-not (Test-Path -LiteralPath $path)) { throw }
    }
}

function Stop-IfRequested {
    if (Test-Path -LiteralPath $script:manifest.kill_switch) {
        $stop = Get-Item -LiteralPath $script:manifest.kill_switch
        Write-LauncherReceipt 'stopped' ([ordered]@{
            reason_code = 'KILL_SWITCH_PRESENT'
            stop_created_at_utc = $stop.CreationTimeUtc.ToString('o')
            stop_modified_at_utc = $stop.LastWriteTimeUtc.ToString('o')
            python_started = $false
        })
        exit 0
    }
}

try {
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    $manifestSha256 = (Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $failureCode = 'MANIFEST_INVALID'
    if ($manifest.schema_version -ne 1 -or $manifest.owner_marker -ne 'ASP_MLB_V18_UNATTENDED_OWNER_V1') {
        throw 'Unrecognized MLB V18 deployment manifest.'
    }
    Stop-IfRequested
    $failureCode = 'LAUNCHER_PATH_MISMATCH'
    if ([IO.Path]::GetFullPath($PSCommandPath) -ne [IO.Path]::GetFullPath($manifest.launcher_path)) {
        throw 'Launcher path does not match the pinned deployment.'
    }
    $failureCode = 'OWNER_IDENTITY_MISMATCH'
    if ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ne $manifest.owner_sid) {
        throw 'Execution identity does not match the registered deployment owner.'
    }
    $failureCode = 'PYTHON_EXECUTABLE_MISMATCH'
    if ((Get-FileHash -LiteralPath $manifest.python_executable -Algorithm SHA256).Hash -ne $manifest.python_sha256) {
        throw 'Pinned Python executable changed; rebuild and review the deployment.'
    }
    $failureCode = 'PINNED_CODE_FILE_SET_MISMATCH'
    $expectedFiles = @($manifest.code_hashes | ForEach-Object { $_.path })
    $actualFiles = @(
        foreach ($directory in @('scripts', 'server', 'tools')) {
            $directoryPath = Join-Path $manifest.code_root $directory
            if (Test-Path -LiteralPath $directoryPath) {
                Get-ChildItem -LiteralPath $directoryPath -Recurse -File |
                    Where-Object { $_.Extension.ToLowerInvariant() -in @('.py', '.json', '.ps1', '.toml', '.yaml', '.yml') -and $_.FullName -notmatch '[\\/]__pycache__[\\/]' } |
                    ForEach-Object { $_.FullName.Substring($manifest.code_root.Length + 1).Replace('\', '/') }
            }
        }
        Get-ChildItem -LiteralPath $manifest.code_root -File |
            Where-Object { $_.Extension.ToLowerInvariant() -in @('.py', '.json', '.ps1', '.toml', '.yaml', '.yml') } |
            ForEach-Object { $_.Name }
    )
    if (Compare-Object ($expectedFiles | Sort-Object) ($actualFiles | Sort-Object)) {
        throw 'The pinned deployment file set changed; rebuild and review the deployment.'
    }
    foreach ($entry in $manifest.code_hashes) {
        $failureCode = 'PINNED_CODE_HASH_MISMATCH'
        $failedRelativePath = $entry.path
        $path = [IO.Path]::GetFullPath((Join-Path $manifest.code_root $entry.path))
        if (-not $path.StartsWith($manifest.code_root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Code hash entry escapes the pinned deployment.'
        }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $entry.sha256) {
            throw "Pinned code changed: $($entry.path). Rebuild and review the deployment."
        }
        if ($null -eq $entry.bytes -or (Get-Item -LiteralPath $path).Length -ne $entry.bytes) {
            $failureCode = 'PINNED_CODE_BYTES_MISMATCH'
            throw "Pinned code byte count changed: $($entry.path). Rebuild and review the deployment."
        }
    }
    $failedRelativePath = $null
    $codeValidated = $true
    # A kill-on-close Job Object owns this launcher and all inherited children.
    # If Task Scheduler terminates the 60-minute action, its Python descendants
    # cannot survive as orphan workers and overlap a later trigger.
    $failureCode = 'PROCESS_TREE_GUARD_FAILED'
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class MlbV18ProcessTreeGuard {
    static IntPtr retainedJob;
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
        public long ProcessTime, JobTime;
        public uint Flags;
        public UIntPtr MinWorkingSet, MaxWorkingSet;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters {
        public ulong ReadOperations, WriteOperations, OtherOperations;
        public ulong ReadBytes, WriteBytes, OtherBytes;
    }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
        public BasicLimits Basic;
        public IoCounters Io;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimits limits, uint length);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    public static void Protect() {
        var job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        var limits = new ExtendedLimits();
        limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (!SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(typeof(ExtendedLimits))) ||
            !AssignProcessToJobObject(job, GetCurrentProcess())) {
            var code = Marshal.GetLastWin32Error();
            CloseHandle(job);
            throw new Win32Exception(code);
        }
        // Retain until process exit; explicitly closing would kill our own task.
        retainedJob = job;
    }
}
'@
    [MlbV18ProcessTreeGuard]::Protect()
    $processTreeGuarded = $true
    # Do not import user profiles, activate a shell venv, or read/log secrets.
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONUNBUFFERED = '1'
    $env:ASP_V18_REPOSITORY_ROOT = $manifest.repository_root
    $env:ASP_V18_CODE_ROOT = $manifest.code_root
    $env:MLB_V18_DEPLOYMENT_MANIFEST = [IO.Path]::GetFullPath($ManifestPath)
    $env:MLB_V18_DEPLOYMENT_MANIFEST_SHA256 = $manifestSha256
    $env:MLB_V18_DEPLOYED_COMMIT = $manifest.deployed_commit
    $env:MLB_V18_UNATTENDED_OWNER = if ($ScheduledInvocation) { 'windows-task-scheduler' } else { 'manual-pinned-launcher-verification' }
    Set-Location -LiteralPath $manifest.code_root
    Stop-IfRequested
    $failureCode = 'LAUNCHER_READY_RECEIPT_FAILED'
    Write-LauncherReceipt 'launcher_ready' ([ordered]@{
        hashed_code_files = @($manifest.code_hashes).Count
        execution_policy = (Get-ExecutionPolicy).ToString()
        python_sha256 = $manifest.python_sha256
        python_started = $false
    })
    $failureCode = 'PYTHON_LAUNCH_FAILED'
    if ($RunNow) { & $manifest.python_executable -B $manifest.runner_path --run-now }
    else { & $manifest.python_executable -B $manifest.runner_path }
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) { $exitCode = 1 }
    $failureCode = 'LAUNCHER_COMPLETION_RECEIPT_FAILED'
    $completionStatus = if ($exitCode -eq 0) { 'launcher_completed' } else { 'runner_failed' }
    Write-LauncherReceipt $completionStatus ([ordered]@{python_started=$true; python_exit_code=$exitCode})
}
catch {
    # The runner owns operational evidence. Keep launcher failures narrowly
    # scoped: exception text is deliberately omitted because it can include data.
    $exitCode = 1
    $nativeError = $_.Exception
    while ($nativeError.InnerException) { $nativeError = $nativeError.InnerException }
    $nativeCode = if ($nativeError -is [ComponentModel.Win32Exception]) { $nativeError.NativeErrorCode } else { $null }
    $failure = [ordered]@{
        failure_code = $failureCode
        exception_type = $_.Exception.GetType().FullName
        underlying_exception_type = $nativeError.GetType().FullName
        hresult = $nativeError.HResult
        native_error_code = $nativeCode
        failed_relative_path = $failedRelativePath
    }
    try { Write-LauncherReceipt 'launcher_failed' $failure }
    catch {
        [Console]::Error.WriteLine('LAUNCHER_FAILURE_RECEIPT_WRITE_FAILED')
    }
    [Console]::Error.WriteLine($failureCode)
}
exit $exitCode
