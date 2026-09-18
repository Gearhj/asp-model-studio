param(
    [string]$RepositoryRoot = 'C:\Users\james\asp-model-studio',
    [string]$BindingPath = '',
    [string]$ReceiptRoot = ''
)
$ErrorActionPreference = 'Stop'
if (-not $BindingPath) { $BindingPath = Join-Path $RepositoryRoot '.runtime\cfb-gen1-slate-publisher\deployment.json' }
if (-not $ReceiptRoot) { $ReceiptRoot = Join-Path $RepositoryRoot '.runtime\cfb-gen1-slate-publisher\launcher-receipts' }
$invocation = [Guid]::NewGuid().ToString('N')
$started = [DateTimeOffset]::UtcNow.ToString('o')
New-Item -ItemType Directory -Path $ReceiptRoot -Force | Out-Null
$prefix = Join-Path $ReceiptRoot $invocation
$code = 1
$pythonCode = $null
$result = $null
$errorText = $null
$utf8 = New-Object Text.UTF8Encoding($false)
# Start and final receipts remain separately immutable. A missing final is an
# interrupted launcher, never successful execution inferred from a stale receipt.
[IO.File]::WriteAllText($prefix + '.started.json', (@{schema='CFB_SLATE_LAUNCHER_START_V1';invocationId=$invocation;startedAtUtc=$started} | ConvertTo-Json -Compress), $utf8)
try {
    $binding = Get-Content -LiteralPath $BindingPath -Raw | ConvertFrom-Json
    $actual = (Get-FileHash -LiteralPath $binding.releasePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $binding.releaseSha256) { throw 'Release hash mismatch' }
    $manifest = Join-Path $PSScriptRoot '..\deployment-manifest.json'
    if ((Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant() -ne $binding.deploymentManifestSha256) { throw 'Launcher deployment mismatch' }
    $python = Join-Path $RepositoryRoot '.venv\Scripts\python.exe'
    $script = Join-Path $PSScriptRoot 'run_cfb_gen1_slate_publisher.py'
    $resultPath = $prefix + '.runner-result.json'
    $captureArgs = @()
    if ($binding.capturePointer) { $captureArgs = @('--capture-pointer',$binding.capturePointer) }
    if ($binding.networkEnabled) {
        if (-not $binding.grantPath -or -not $binding.grantSha256) { throw 'Exact recurring refresh grant required' }
        $captureArgs += @('--enable-network','--grant',$binding.grantPath,'--grant-sha256',$binding.grantSha256)
    }
    & $python $script --release $binding.releasePath --release-sha256 $binding.releaseSha256 --input-pointer $binding.inputPointer --state-root $binding.stateRoot --exchange-root $binding.exchangeRoot --result-file $resultPath @captureArgs 1> ($prefix + '.stdout.txt') 2> ($prefix + '.stderr.txt')
    $pythonCode = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath $resultPath)) { throw 'Runner did not leave a result receipt' }
    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    if ($result.exitCode -ne $pythonCode) { throw 'Runner receipt/exit mismatch' }
    if ((Get-FileHash -LiteralPath $result.receipt.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $result.receipt.sha256) { throw 'Runner receipt hash mismatch' }
    $code = $pythonCode
} catch {
    $errorText = $_.Exception.Message
    $code = 1
} finally {
    $receipt = [ordered]@{schema='CFB_GEN1_SLATE_LAUNCHER_RECEIPT_V1';invocationId=$invocation;
        startedAtUtc=$started;completedAtUtc=[DateTimeOffset]::UtcNow.ToString('o');
        pythonExitCode=$pythonCode;wrapperExitCode=$code;runner=$result;error=$errorText;
        disposition=$(if ($errorText) {'LAUNCHER_FAILED'} elseif ($result) {$result.disposition} else {'FAILED'});
        bindingPath=$BindingPath;providerCalls=$(if ($result) {$result.providerCalls} else {$null});
        providerBytes=$(if ($result) {$result.providerBytes} else {$null});aispWrites=0}
    [IO.File]::WriteAllText($prefix + '.json', ($receipt | ConvertTo-Json -Depth 12 -Compress), $utf8)
    $sha = (Get-FileHash -LiteralPath ($prefix + '.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Output ($receipt | ConvertTo-Json -Depth 12 -Compress)
    Write-Output ('launcher_receipt_sha256=' + $sha)
}
exit $code
