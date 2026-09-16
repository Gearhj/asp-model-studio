<#
.SYNOPSIS
Runs only the immutable Codex Phase 7D.5A.3 red Silver acceptance suite.

The baseline is intentionally RED at 5ec6c9b. A nonzero pytest result is the
expected authoring-phase outcome. All evidence and mutable state are preserved
under a fresh OS-temporary root; the shared repository runtime is inventoried
metadata-only before and after and is never selected as a runtime root.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ExpectedBranch = "phase7d5a3-codex-red-silver-gate"
$SourceBranch = "phase7d5a2-silver-publication-integrity-closure"
$BaselineHead = "5ec6c9b7267f0d209fbc93c4397315a9fe5fe216"
$ExpectedMain = "924db29511f93909f9d785855bfa056775443690"
$SuiteRel = "tests/codex_phase7d5a3_red_gate"
$RunnerRel = "scripts/run_phase7d5a3_codex_red_gate.ps1"
$PreservedReport = "docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Repo
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Required repository Python environment not found: $Python"
}

function Get-MetadataInventory([string]$InventoryRoot) {
    $resolved = (Resolve-Path -LiteralPath $InventoryRoot).Path
    $files = @(Get-ChildItem -LiteralPath $resolved -Recurse -File -Force -ErrorAction Stop | Sort-Object FullName)
    $dirs = @(Get-ChildItem -LiteralPath $resolved -Recurse -Directory -Force -ErrorAction Stop | Sort-Object FullName)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $fileText = ($files | ForEach-Object {
        $_.FullName.Substring($resolved.Length).Replace('\', '/') + '|' + $_.Length + '|' +
            $_.CreationTimeUtc.Ticks + '|' + $_.LastWriteTimeUtc.Ticks + '|' + [int]$_.Attributes
    }) -join "`n"
    $dirText = ($dirs | ForEach-Object {
        $_.FullName.Substring($resolved.Length).Replace('\', '/') + '|' +
            $_.CreationTimeUtc.Ticks + '|' + $_.LastWriteTimeUtc.Ticks + '|' + [int]$_.Attributes
    }) -join "`n"
    [ordered]@{
        root = $resolved
        inventoryMode = 'PATH_LENGTH_CREATION_MTIME_ATTRIBUTES_NO_FILE_CONTENT_OPEN'
        files = $files.Count
        directories = $dirs.Count
        bytes = [int64](($files | Measure-Object Length -Sum).Sum)
        fileInventorySha256 = [Convert]::ToHexString(
            $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($fileText))
        ).ToLowerInvariant()
        directoryInventorySha256 = [Convert]::ToHexString(
            $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($dirText))
        ).ToLowerInvariant()
    }
}

function Test-PathWithin([string]$Child, [string]$Parent) {
    $childFull = [IO.Path]::GetFullPath($Child).TrimEnd('\', '/')
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    return (
        $childFull.Equals($parentFull, [StringComparison]::OrdinalIgnoreCase) -or
        $childFull.StartsWith($parentFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
    )
}

function Assert-NoExistingReparseComponent([string]$Candidate) {
    $cursor = [IO.Path]::GetFullPath($Candidate)
    while ($true) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Mutable root traverses a reparse point: $cursor"
            }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { break }
        $cursor = $parent.FullName
    }
}

function Assert-SafeExternalMutablePath([string]$Candidate, [string]$AuditParent = '') {
    if (-not [IO.Path]::IsPathFullyQualified($Candidate)) {
        throw "Mutable path must be absolute: $Candidate"
    }
    $full = [IO.Path]::GetFullPath($Candidate)
    foreach ($forbidden in @(
        $Repo,
        (Join-Path $Repo '.runtime'),
        'C:\Users\james\asp-model-exchange',
        'C:\Users\james\asp-data-staging'
    )) {
        if (Test-PathWithin $full $forbidden) {
            throw "Mutable path is inside a forbidden authority: $full"
        }
    }
    if ($AuditParent -and -not (Test-PathWithin $full $AuditParent)) {
        throw "Mutable child escapes the disposable audit root: $full"
    }
    Assert-NoExistingReparseComponent $full
}

function Assert-OnlyAuthorizedPaths {
    $lines = @(git status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw "git status failed" }
    foreach ($line in $lines) {
        if ($line.Length -lt 4) { continue }
        $path = $line.Substring(3).Replace('\', '/')
        if ($path -eq $PreservedReport) {
            if ($line.Substring(0, 2) -ne '??') {
                throw "Preserved report no longer has the exact expected untracked disposition: $line"
            }
            continue
        }
        if ($path -eq $RunnerRel) { continue }
        if ($path.StartsWith("$SuiteRel/", [StringComparison]::Ordinal)) { continue }
        throw "Unauthorized worktree path present: $line"
    }
    $changed = @(git diff --name-only $BaselineHead --)
    if ($LASTEXITCODE -ne 0) { throw "git diff against the exact baseline failed" }
    foreach ($pathValue in $changed) {
        $path = $pathValue.Replace('\', '/')
        if ($path -eq $RunnerRel) { continue }
        if ($path.StartsWith("$SuiteRel/", [StringComparison]::Ordinal)) { continue }
        throw "Branch contains a change outside the red-gate boundary: $path"
    }
}

function Assert-AcceptanceManifest([string]$Path, [string[]]$CollectedNodes) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Acceptance manifest missing: $Path"
    }
    $manifest = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $rootNames = @($manifest.PSObject.Properties.Name | Sort-Object)
    $expectedRootNames = @(
        'baselineHead', 'builderConstraints', 'findings', 'manifestVersion',
        'repair5Disposition', 'schemaVersion', 'suiteId'
    ) | Sort-Object
    if (($rootNames -join '|') -ne ($expectedRootNames -join '|')) {
        throw "Acceptance manifest root schema is not exact"
    }
    if ($manifest.schemaVersion -ne 'CODEX_PHASE7D5A3_ACCEPTANCE_MANIFEST_V1' -or
        $manifest.manifestVersion -ne 1 -or $manifest.baselineHead -ne $BaselineHead) {
        throw "Acceptance manifest identity/baseline mismatch"
    }
    foreach ($name in @('schemaVersion', 'suiteId', 'baselineHead', 'repair5Disposition')) {
        if ($manifest.$name -isnot [string] -or [string]::IsNullOrWhiteSpace($manifest.$name)) {
            throw "Acceptance manifest field $name must be a nonempty string"
        }
    }
    if ($manifest.manifestVersion -isnot [long] -and $manifest.manifestVersion -isnot [int]) {
        throw "Acceptance manifest version must be an integer"
    }
    if ($manifest.repair5Disposition -ne 'PASS_NOT_A_RED_FINDING') {
        throw "Acceptance manifest incorrectly creates an R5 red finding"
    }
    $expectedFindingIds = @(
        'R1_SEASON_AND_COLUMN_AUTHORITY',
        'R2_SOURCE_AND_TRANSFORM_AUTHORITY',
        'R3_RELATIONAL_SILVER_VERIFICATION',
        'R4_CANONICAL_QUARANTINE_BOUNDARY',
        'R6_COMPLETE_REPARSE_CONTAINMENT',
        'R7_DATA_HERMETIC_GATE',
        'R8_COLLECTION_AND_SKIP_GOVERNANCE'
    )
    $actualFindingIds = @($manifest.findings | ForEach-Object { $_.findingId })
    if (($actualFindingIds -join '|') -ne ($expectedFindingIds -join '|')) {
        throw "Acceptance manifest finding IDs/order are not exact"
    }
    $findingNames = @(
        'affectedProductionBoundary', 'auditFinding', 'currentExpectedFailureBehavior',
        'findingId', 'pytestNodeIds', 'requiredCorrectedBehavior',
        'subprocessRequired', 'windowsOnly'
    ) | Sort-Object
    foreach ($finding in $manifest.findings) {
        if ((@($finding.PSObject.Properties.Name | Sort-Object) -join '|') -ne ($findingNames -join '|')) {
            throw "Finding $($finding.findingId) does not match the strict finding schema"
        }
        foreach ($name in @(
            'affectedProductionBoundary', 'auditFinding', 'currentExpectedFailureBehavior',
            'findingId', 'requiredCorrectedBehavior'
        )) {
            if ($finding.$name -isnot [string] -or [string]::IsNullOrWhiteSpace($finding.$name)) {
                throw "Finding $($finding.findingId) field $name must be a nonempty string"
            }
        }
        if ($finding.windowsOnly -isnot [bool] -or $finding.subprocessRequired -isnot [bool]) {
            throw "Finding $($finding.findingId) platform/subprocess fields must be booleans"
        }
        if ($finding.pytestNodeIds -is [string] -or @($finding.pytestNodeIds).Count -eq 0) {
            throw "Finding $($finding.findingId) has no pytest nodes"
        }
        foreach ($node in $finding.pytestNodeIds) {
            if ($node -isnot [string] -or [string]::IsNullOrWhiteSpace($node)) {
                throw "Finding $($finding.findingId) has a non-string/empty pytest node"
            }
            if ($CollectedNodes -notcontains [string]$node) {
                throw "Acceptance-manifest node was not collected exactly: $node"
            }
        }
    }
    $manifestNodes = @($manifest.findings | ForEach-Object { @($_.pytestNodeIds) })
    if (@($manifestNodes | Sort-Object -Unique).Count -ne $manifestNodes.Count) {
        throw "Acceptance manifest assigns one or more pytest nodes to multiple findings"
    }
    if ((@($manifestNodes | Sort-Object) -join '|') -ne (@($CollectedNodes | Sort-Object) -join '|')) {
        throw "Acceptance manifest must cover every collected red-gate node exactly once"
    }
    $constraints = $manifest.builderConstraints
    $constraintNames = @($constraints.PSObject.Properties.Name | Sort-Object)
    $expectedConstraintNames = @(
        'prohibitedActions', 'runnerImmutableToBuilder', 'testsImmutableToBuilder'
    ) | Sort-Object
    if (($constraintNames -join '|') -ne ($expectedConstraintNames -join '|')) {
        throw "Builder constraints do not match the strict schema"
    }
    $requiredVerbs = @('editing', 'deleting', 'renaming', 'weakening', 'skipping', 'replacing', 'bypassing')
    if ($constraints.prohibitedActions -is [string] -or
        ((@($constraints.prohibitedActions | Sort-Object) -join '|') -ne (@($requiredVerbs | Sort-Object) -join '|'))) {
        throw "Builder prohibited-actions list is not exact"
    }
    if ($constraints.testsImmutableToBuilder -isnot [bool] -or
        $constraints.runnerImmutableToBuilder -isnot [bool] -or
        -not $constraints.testsImmutableToBuilder -or -not $constraints.runnerImmutableToBuilder) {
        throw "Builder immutability constraints are not fail-closed"
    }
}

$branchRaw = @(git branch --show-current)
if ($LASTEXITCODE -ne 0) { throw "git branch --show-current failed" }
$branch = ($branchRaw -join '').Trim()
if ($branch -ne $ExpectedBranch) { throw "Wrong branch: $branch (expected $ExpectedBranch)" }
$sourceRaw = @(git rev-parse $SourceBranch)
if ($LASTEXITCODE -ne 0) { throw "git rev-parse of source branch failed" }
$sourceHead = ($sourceRaw -join '').Trim()
if ($sourceHead -ne $BaselineHead) { throw "Source baseline moved: $sourceHead" }
$mainRaw = @(git rev-parse main)
if ($LASTEXITCODE -ne 0) { throw "git rev-parse main failed" }
if (($mainRaw -join '').Trim() -ne $ExpectedMain) { throw "main moved from $ExpectedMain" }
$headRaw = @(git rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($headRaw -join '').Trim())) {
    throw "git rev-parse HEAD failed"
}
git merge-base --is-ancestor $BaselineHead HEAD
if ($LASTEXITCODE -ne 0) { throw "Current branch does not descend from exact baseline $BaselineHead" }
Assert-OnlyAuthorizedPaths

$AuditRoot = [IO.Path]::GetFullPath((
    Join-Path ([IO.Path]::GetTempPath()) ("codex-phase7d5a3-red-gate-" + [Guid]::NewGuid().ToString('N'))
))
$RuntimeRoot = Join-Path $AuditRoot "runtime"
$TempRoot = Join-Path $AuditRoot "temp"
$PytestRoot = Join-Path $TempRoot "pytest"
$ModelExchangeRoot = Join-Path $AuditRoot "model-exchange-disabled"
Assert-SafeExternalMutablePath $AuditRoot
foreach ($path in @($RuntimeRoot, $TempRoot, $PytestRoot, $ModelExchangeRoot)) {
    Assert-SafeExternalMutablePath $path $AuditRoot
}
foreach ($path in @($AuditRoot, $RuntimeRoot, $TempRoot, $PytestRoot, $ModelExchangeRoot)) {
    New-Item -ItemType Directory -Path $path -ErrorAction Stop | Out-Null
}

$SharedRuntime = Join-Path $Repo ".runtime"
$BeforePath = Join-Path $AuditRoot "shared-runtime-before.json"
$AfterPath = Join-Path $AuditRoot "shared-runtime-after.json"
$HarnessErrorPath = Join-Path $AuditRoot "harness-error.txt"
$before = Get-MetadataInventory $SharedRuntime
$before | ConvertTo-Json | Set-Content -LiteralPath $BeforePath -Encoding utf8
$runtimeSame = $false
$finalExitCode = 3

try {
    $env:CODEX_PHASE7D5A3_AUDIT_ROOT = $AuditRoot
    $env:ASP_MODEL_STUDIO_RUNTIME_ROOT = $RuntimeRoot
    $env:ASP_REQUIRE_ISOLATED_RUNTIME = '1'
    $env:TEMP = $TempRoot
    $env:TMP = $TempRoot
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONPATH = $Repo
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
    $env:ASP_MODEL_EXCHANGE_ROOT = $ModelExchangeRoot

    $CollectedPath = Join-Path $AuditRoot "collected-nodes.txt"
    $CollectionManifest = Join-Path $AuditRoot "external-access-collection.json"
    $ExecutionManifest = Join-Path $AuditRoot "external-access-execution.json"
    $JunitPath = Join-Path $AuditRoot "red-gate-junit.xml"
    $FailurePath = Join-Path $AuditRoot "failure-signatures.json"
    $SummaryPath = Join-Path $AuditRoot "runner-summary.json"
    $ManifestPath = Join-Path $Repo "$SuiteRel\acceptance_manifest.json"

    if ($CollectionManifest -eq $ExecutionManifest) {
        throw "Collection and execution external-access manifests must be distinct"
    }
    $env:CODEX_PHASE7D5A3_EXTERNAL_ACCESS_MANIFEST = $CollectionManifest
    & $Python -B -m pytest $SuiteRel --collect-only -q -p no:cacheprovider 2>&1 |
        Set-Content -LiteralPath $CollectedPath -Encoding utf8
    $collectRc = $LASTEXITCODE
    if ($collectRc -ne 0) { throw "Red-gate collection failed" }
    $collected = @(
        Get-Content -LiteralPath $CollectedPath |
            Where-Object { $_ -match '::' } |
            ForEach-Object { $_.Trim().Replace('\', '/') }
    )
    if ($collected.Count -eq 0 -or @($collected | Sort-Object -Unique).Count -ne $collected.Count) {
        throw "Collected-node inventory is empty or contains duplicates"
    }
    Assert-AcceptanceManifest $ManifestPath $collected

    $env:CODEX_PHASE7D5A3_EXTERNAL_ACCESS_MANIFEST = $ExecutionManifest
    & $Python -B -m pytest $SuiteRel -vv -rs -p no:cacheprovider --basetemp $PytestRoot --junitxml $JunitPath
    $pytestRc = $LASTEXITCODE

    if (-not (Test-Path -LiteralPath $JunitPath -PathType Leaf)) {
        throw "JUnit report missing"
    }
    [xml]$junit = Get-Content -LiteralPath $JunitPath -Raw
    $cases = @($junit.SelectNodes('//testcase'))
    $signatures = @()
    foreach ($case in $cases) {
        $status = 'passed'
        $message = ''
        $failureNode = $case.SelectSingleNode('failure')
        $errorNode = $case.SelectSingleNode('error')
        $skippedNode = $case.SelectSingleNode('skipped')
        if ($null -ne $failureNode) { $status = 'failed'; $message = [string]$failureNode.GetAttribute('message') }
        elseif ($null -ne $errorNode) { $status = 'error'; $message = [string]$errorNode.GetAttribute('message') }
        elseif ($null -ne $skippedNode) { $status = 'skipped'; $message = [string]$skippedNode.GetAttribute('message') }
        $name = [string]$case.GetAttribute('name')
        $file = ([string]$case.GetAttribute('file')).Replace('\', '/')
        $nodeId = if ($file) { "$file::$name" } else { '' }
        if (-not $nodeId -or $collected -notcontains $nodeId) {
            $matches = @($collected | Where-Object { $_.EndsWith("::$name", [StringComparison]::Ordinal) })
            if ($matches.Count -ne 1) {
                throw "JUnit node cannot be mapped exactly to collection: classname=$($case.GetAttribute('classname')) name=$name"
            }
            $nodeId = $matches[0]
        }
        $signatures += [ordered]@{
            nodeId = $nodeId
            classname = [string]$case.GetAttribute('classname')
            name = $name
            status = $status
            message = $message
        }
    }
    $caseNodes = @($signatures | ForEach-Object { $_.nodeId })
    if ($cases.Count -ne $collected.Count -or
        @($caseNodes | Sort-Object -Unique).Count -ne $caseNodes.Count -or
        ((@($caseNodes | Sort-Object) -join '|') -ne (@($collected | Sort-Object) -join '|'))) {
        throw "Collection/JUnit execution parity is not exact"
    }
    $signatures | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $FailurePath -Encoding utf8
    $passed = @($signatures | Where-Object { $_.status -eq 'passed' }).Count
    $failed = @($signatures | Where-Object { $_.status -eq 'failed' }).Count
    $errors = @($signatures | Where-Object { $_.status -eq 'error' }).Count
    $skipped = @($signatures | Where-Object { $_.status -eq 'skipped' }).Count
    if ($pytestRc -ne 1 -or $failed -eq 0 -or $errors -ne 0 -or $skipped -ne 0) {
        throw "Baseline is not a clean intentional red state (pytest=$pytestRc failed=$failed errors=$errors skipped=$skipped)"
    }
    $acceptance = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    foreach ($finding in $acceptance.findings) {
        $findingStatuses = @(
            $signatures |
                Where-Object { @($finding.pytestNodeIds) -contains $_.nodeId } |
                ForEach-Object { $_.status }
        )
        if ($findingStatuses -notcontains 'failed') {
            throw "Finding $($finding.findingId) has no red baseline node"
        }
    }

    $externalSafe = $true
    $expectedExternalNames = @(
        'attempts', 'auditRoot', 'bronzeRowsOpened', 'networkAttempts', 'providerCalls',
        'runtimeRoot', 'schemaVersion', 'sealedRowsOpened', 'unexpectedExistingExternalDataOpens'
    ) | Sort-Object
    foreach ($manifestFile in @($CollectionManifest, $ExecutionManifest)) {
        if (-not (Test-Path -LiteralPath $manifestFile -PathType Leaf)) {
            $externalSafe = $false
            continue
        }
        $report = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
        $actualNames = @($report.PSObject.Properties.Name | Sort-Object)
        if (($actualNames -join '|') -ne ($expectedExternalNames -join '|') -or
            $report.schemaVersion -ne 'CODEX_PHASE7D5A3_EXTERNAL_ACCESS_V1' -or
            $report.auditRoot -ne $AuditRoot -or $report.runtimeRoot -ne $RuntimeRoot -or
            $report.bronzeRowsOpened -isnot [bool] -or $report.sealedRowsOpened -isnot [bool] -or
            (($report.providerCalls -isnot [long]) -and ($report.providerCalls -isnot [int])) -or
            @($report.unexpectedExistingExternalDataOpens).Count -ne 0 -or
            @($report.networkAttempts).Count -ne 0 -or
            $report.bronzeRowsOpened -or $report.sealedRowsOpened -or $report.providerCalls -ne 0 -or
            @($report.attempts | Where-Object { $_.classification -eq 'shared_runtime' }).Count -ne 0) {
            $externalSafe = $false
        }
    }
    if (-not $externalSafe) { throw "External-access evidence is missing, malformed, or unsafe" }

    $summary = [ordered]@{
        schemaVersion = 'CODEX_PHASE7D5A3_RUNNER_SUMMARY_V1'
        baselineHead = $BaselineHead
        branch = $branch
        auditRoot = $AuditRoot
        collected = $collected.Count
        tests = $cases.Count
        passed = $passed
        failed = $failed
        errors = $errors
        skipped = $skipped
        pytestExitCode = $pytestRc
        sharedRuntimeMetadataIdentical = $false
        sharedRuntimeInventoryMode = $before.inventoryMode
        externalAccessSafe = $externalSafe
        externalAccessManifests = @($CollectionManifest, $ExecutionManifest)
        junit = $JunitPath
        nodeInventory = $CollectedPath
        failureSignatures = $FailurePath
    }
    $summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $SummaryPath -Encoding utf8
    $finalExitCode = $pytestRc
}
catch {
    $_ | Out-String | Set-Content -LiteralPath $HarnessErrorPath -Encoding utf8
    Write-Host "Red-gate harness failure; evidence preserved at ${AuditRoot}: $($_.Exception.Message)" -ForegroundColor Red
    $finalExitCode = 3
}
finally {
    try {
        $after = Get-MetadataInventory $SharedRuntime
        $after | ConvertTo-Json | Set-Content -LiteralPath $AfterPath -Encoding utf8
        $runtimeSame = (
            $before.files -eq $after.files -and
            $before.directories -eq $after.directories -and
            $before.bytes -eq $after.bytes -and
            $before.fileInventorySha256 -eq $after.fileInventorySha256 -and
            $before.directoryInventorySha256 -eq $after.directoryInventorySha256
        )
        if (-not $runtimeSame) {
            $finalExitCode = 3
            "Shared runtime metadata inventory changed" |
                Add-Content -LiteralPath $HarnessErrorPath -Encoding utf8
        }
        $summaryCandidate = Join-Path $AuditRoot 'runner-summary.json'
        if (Test-Path -LiteralPath $summaryCandidate -PathType Leaf) {
            $savedSummary = Get-Content -LiteralPath $summaryCandidate -Raw | ConvertFrom-Json
            $savedSummary.sharedRuntimeMetadataIdentical = $runtimeSame
            $savedSummary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryCandidate -Encoding utf8
            $savedSummary | ConvertTo-Json -Depth 5
        }
    }
    catch {
        $finalExitCode = 3
        $_ | Out-String | Add-Content -LiteralPath $HarnessErrorPath -Encoding utf8
    }
    Write-Host "Evidence preserved at: $AuditRoot"
}

exit $finalExitCode
