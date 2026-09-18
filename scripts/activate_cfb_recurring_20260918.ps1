param(
    [ValidateSet('Plan','Install','Verify')][string]$Mode = 'Plan',
    [string]$EvidenceRoot = 'C:\Users\james\asp-model-studio\outputs\cfb-recurring-activation-20260918-v1'
)
$ErrorActionPreference = 'Stop'
$argsPath = Join-Path $EvidenceRoot 'installation-arguments.json'
$approved = Get-Content -LiteralPath $argsPath -Raw | ConvertFrom-Json
$installer = Join-Path ('C:\Users\james\asp-model-studio\.deployments\cfb-gen1-slate-publisher\' + $approved.DeploymentId) 'scripts\install_cfb_gen1_slate_publisher.ps1'
$shell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$callArgs = @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$installer,'-Mode',$Mode)
foreach ($entry in $approved.PSObject.Properties) {
    if ($entry.Name -eq 'EnableNetwork') {
        if ($entry.Value -ne $true) { throw 'Exact network authorization required' }
        $callArgs += '-EnableNetwork'
    } else {
        $callArgs += @((('-' + $entry.Name)), ([string]$entry.Value))
    }
}
$stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
$prefix = Join-Path $EvidenceRoot ($Mode.ToLowerInvariant() + '-' + $stamp)
$start = [DateTimeOffset]::UtcNow.ToString('o')
$ErrorActionPreference = 'Continue'
& $shell @callArgs 1> ($prefix + '.stdout.txt') 2> ($prefix + '.stderr.txt')
$result = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
$receipt = [ordered]@{
    schema = 'CFB_SUPPORTED_INSTALLER_INVOCATION_V1'
    mode = $Mode
    startedAtUtc = $start
    completedAtUtc = [DateTimeOffset]::UtcNow.ToString('o')
    installer = $installer
    installerSha256 = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    argumentsPath = $argsPath
    argumentsSha256 = (Get-FileHash -LiteralPath $argsPath -Algorithm SHA256).Hash.ToLowerInvariant()
    stdout = $prefix + '.stdout.txt'
    stderr = $prefix + '.stderr.txt'
    exitCode = $result
}
$json = $receipt | ConvertTo-Json -Depth 5 -Compress
[IO.File]::WriteAllText($prefix + '.json', $json, (New-Object Text.UTF8Encoding($false)))
Write-Output $json
exit $result
