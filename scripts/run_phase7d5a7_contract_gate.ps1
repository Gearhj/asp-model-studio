<#
.SYNOPSIS
Runs the reconciled Phase 7D.5A.7 original, delta, and contract authorities.

All Python processes use fresh external roots.  Current production is expected
to remain intentionally red at D1/D2; exact status partitions are contractual.
No production implementation is supplied or patched by this runner.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedBranch = 'phase7d5a7-codex-acceptance-contract-reconciliation'
$ReconciliationBase = '8ab74422928b8483402d247c3822a0171f766a1b'
$ExpectedMain = '924db29511f93909f9d785855bfa056775443690'
$PreservedReport = 'docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md'
$PreservedReportSha256 = '72c5a70d12a61f04ffdebfb2d3a5a11b17236b29abd0d9d36fd035ddd12593a6'
$OriginalSuite = 'tests/codex_phase7d5a3_red_gate'
$DeltaSuite = 'tests/codex_phase7d5a5_delta_red_gate'
$ContractSuite = 'tests/codex_phase7d5a7_contract'
$RunnerRel = 'scripts/run_phase7d5a7_contract_gate.ps1'
$AllowedChanges = @(
    'tests/codex_phase7d5a3_red_gate/test_r1_r2.py',
    'tests/codex_phase7d5a3_red_gate/acceptance_manifest.json',
    'tests/codex_phase7d5a5_delta_red_gate/test_d1_d2.py',
    'tests/codex_phase7d5a5_delta_red_gate/acceptance_manifest.json',
    'tests/codex_phase7d5a7_contract/',
    $RunnerRel
)

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Repo
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$ContractPath = Join-Path $Repo "$ContractSuite\acceptance_contract.json"
$IssuerCommitted = Join-Path $Repo "$ContractSuite\canonical_synthetic_issuer_registry.json"
$OriginalManifestPath = Join-Path $Repo "$OriginalSuite\acceptance_manifest.json"
$DeltaManifestPath = Join-Path $Repo "$DeltaSuite\acceptance_manifest.json"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Missing Python: $Python" }
if (-not (Test-Path -LiteralPath $ContractPath -PathType Leaf)) { throw "Missing contract: $ContractPath" }
if (-not (Test-Path -LiteralPath $IssuerCommitted -PathType Leaf)) { throw "Missing issuer fixture: $IssuerCommitted" }

function Invoke-GitLines([string[]]$Arguments) {
    $lines = @(& git @Arguments)
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed ($LASTEXITCODE)" }
    return $lines
}

function Test-Within([string]$Child, [string]$Parent) {
    $childFull = [IO.Path]::GetFullPath($Child).TrimEnd('\', '/')
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    return $childFull.Equals($parentFull, [StringComparison]::OrdinalIgnoreCase) -or
        $childFull.StartsWith($parentFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoExistingReparse([string]$Candidate) {
    $cursor = [IO.Path]::GetFullPath($Candidate)
    while ($true) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Mutable path crosses a reparse point: $cursor"
            }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent) { break }
        $cursor = $parent.FullName
    }
}

function Assert-SafeMutablePath([string]$Candidate, [string]$Parent = '') {
    if (-not [IO.Path]::IsPathFullyQualified($Candidate)) { throw "Mutable path must be absolute: $Candidate" }
    $full = [IO.Path]::GetFullPath($Candidate)
    foreach ($forbidden in @(
        $Repo,
        (Join-Path $Repo '.runtime'),
        'C:\Users\james\asp-model-exchange',
        'C:\Users\james\asp-data-staging'
    )) {
        if (Test-Within $full $forbidden) { throw "Mutable path is under forbidden authority: $full" }
    }
    if ($Parent -and -not (Test-Within $full $Parent)) { throw "Mutable child escaped audit root: $full" }
    Assert-NoExistingReparse $full
}

function Get-MetadataInventory([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return [ordered]@{ exists = $false; root = [IO.Path]::GetFullPath($Root); files = 0; directories = 0; bytes = 0; sha256 = '' }
    }
    $resolved = (Resolve-Path -LiteralPath $Root).Path
    $items = @(Get-ChildItem -LiteralPath $resolved -Force -Recurse -ErrorAction Stop | Sort-Object FullName)
    $lines = foreach ($item in $items) {
        $relative = $item.FullName.Substring($resolved.Length).Replace('\', '/')
        if ($item.PSIsContainer) {
            "D|$relative|$($item.CreationTimeUtc.Ticks)|$($item.LastWriteTimeUtc.Ticks)|$([int]$item.Attributes)"
        } else {
            "F|$relative|$($item.Length)|$($item.CreationTimeUtc.Ticks)|$($item.LastWriteTimeUtc.Ticks)|$([int]$item.Attributes)"
        }
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $digest = [Convert]::ToHexString($hasher.ComputeHash($bytes)).ToLowerInvariant() }
    finally { $hasher.Dispose() }
    $files = @($items | Where-Object { -not $_.PSIsContainer })
    return [ordered]@{
        exists = $true
        root = $resolved
        files = $files.Count
        directories = @($items | Where-Object { $_.PSIsContainer }).Count
        bytes = [int64](($files | Measure-Object Length -Sum).Sum)
        sha256 = $digest
        mode = 'PATH_LENGTH_CREATION_MTIME_ATTRIBUTES_NO_CONTENT_READ'
    }
}

function Assert-GitState {
    if ((Invoke-GitLines @('branch', '--show-current'))[0].Trim() -ne $ExpectedBranch) {
        throw "Expected branch $ExpectedBranch"
    }
    if ((Invoke-GitLines @('rev-parse', 'main'))[0].Trim() -ne $ExpectedMain) { throw 'main moved' }
    & git merge-base --is-ancestor $ReconciliationBase HEAD
    if ($LASTEXITCODE -ne 0) { throw 'HEAD is not a descendant of the reconciliation base' }
    foreach ($marker in @('.git\MERGE_HEAD', '.git\rebase-merge', '.git\rebase-apply', '.git\CHERRY_PICK_HEAD', '.git\BISECT_LOG')) {
        if (Test-Path -LiteralPath (Join-Path $Repo $marker)) { throw "Incomplete Git operation: $marker" }
    }
    $changed = @(Invoke-GitLines @('diff', '--name-only', "$ReconciliationBase..HEAD"))
    foreach ($raw in $changed) {
        $path = $raw.Trim().Replace('\', '/')
        $allowed = $false
        foreach ($rule in $AllowedChanges) {
            if ($rule.EndsWith('/') -and $path.StartsWith($rule, [StringComparison]::Ordinal)) { $allowed = $true; break }
            if (-not $rule.EndsWith('/') -and $path -eq $rule) { $allowed = $true; break }
        }
        if (-not $allowed) { throw "Non-auditor change since reconciliation base: $path" }
    }
    $authorityCommits = @(Invoke-GitLines @('log', '--diff-filter=A', '--format=%H', '--reverse', '--', $RunnerRel))
    if ($authorityCommits.Count -eq 0) { throw 'Contract runner has not been committed as an immutable authority' }
    $authorityCommit = $authorityCommits[0].Trim()
    & git diff --exit-code $authorityCommit -- `
        'tests/codex_phase7d5a3_red_gate/test_r1_r2.py' `
        'tests/codex_phase7d5a3_red_gate/acceptance_manifest.json' `
        'tests/codex_phase7d5a5_delta_red_gate/test_d1_d2.py' `
        'tests/codex_phase7d5a5_delta_red_gate/acceptance_manifest.json' `
        $ContractSuite $RunnerRel
    if ($LASTEXITCODE -ne 0) { throw "Acceptance authority changed after authoring commit $authorityCommit" }
    $status = @(Invoke-GitLines @('status', '--porcelain=v1', '--untracked-files=all'))
    foreach ($line in $status) {
        if ($line.Length -lt 4) { continue }
        $path = $line.Substring(3).Replace('\', '/')
        if ($line.Substring(0, 2) -eq '??' -and $path -eq $PreservedReport) { continue }
        throw "Unexpected worktree disposition: $line"
    }
    $reportPath = Join-Path $Repo $PreservedReport
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) { throw 'Preserved report is missing' }
    $reportSha = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($reportSha -ne $PreservedReportSha256) { throw 'Preserved report bytes changed' }
    & git diff --check
    if ($LASTEXITCODE -ne 0) { throw 'git diff --check failed' }
}

function Set-PhaseEnvironment(
    [string]$PhaseRoot,
    [string]$SuiteKind,
    [string]$IssuerPath,
    [string]$CollectionManifest,
    [string]$ExecutionManifest,
    [string]$ExternalManifest,
    [string]$IsolatedManifest
) {
    foreach ($name in @(
        'CODEX_PHASE7D5A3_AUDIT_ROOT', 'CODEX_PHASE7D5A5_AUDIT_ROOT',
        'CODEX_PHASE7D5A3_EXTERNAL_ACCESS_MANIFEST', 'CODEX_PHASE7D5A5_EXTERNAL_ACCESS_MANIFEST',
        'PYTEST_ADDOPTS'
    )) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
    $runtime = Join-Path $PhaseRoot 'runtime'
    $temp = Join-Path $PhaseRoot 'temp'
    $pytestRoot = Join-Path $PhaseRoot 'pytest'
    $exchange = Join-Path $PhaseRoot 'model-exchange-disabled'
    foreach ($path in @($runtime, $temp, $pytestRoot, $exchange)) {
        Assert-SafeMutablePath $path $PhaseRoot
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }
    if ($SuiteKind -eq 'original') {
        $env:CODEX_PHASE7D5A3_AUDIT_ROOT = $PhaseRoot
        $env:CODEX_PHASE7D5A3_EXTERNAL_ACCESS_MANIFEST = $ExternalManifest
    } elseif ($SuiteKind -eq 'delta') {
        $env:CODEX_PHASE7D5A5_AUDIT_ROOT = $PhaseRoot
        $env:CODEX_PHASE7D5A5_EXTERNAL_ACCESS_MANIFEST = $ExternalManifest
    }
    $env:CODEX_PHASE7D5A7_ACTIVE_SUITE_ROOT = $PhaseRoot
    $env:CODEX_PHASE7D5A7_ISSUER_REGISTRY = $IssuerPath
    $env:CODEX_PHASE7D5A7_COLLECTION_MANIFEST = $CollectionManifest
    $env:CODEX_PHASE7D5A7_EXECUTION_MANIFEST = $ExecutionManifest
    $env:ASP_MODEL_STUDIO_RUNTIME_ROOT = $runtime
    $env:ASP_REQUIRE_ISOLATED_RUNTIME = '1'
    $env:ASP_MODEL_EXCHANGE_ROOT = $exchange
    $env:ASP_ISOLATED_TEST_TEMP = $pytestRoot
    $env:ASP_ISOLATED_DATA_MANIFEST = $IsolatedManifest
    $env:TEMP = $temp
    $env:TMP = $temp
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
}

function Assert-ExternalEvidence([string]$ExternalPath, [string]$IsolatedPath, [bool]$RequireExternal) {
    if ($RequireExternal) {
        if (-not (Test-Path -LiteralPath $ExternalPath -PathType Leaf)) { throw "Missing external evidence: $ExternalPath" }
        $external = Get-Content -Raw -LiteralPath $ExternalPath | ConvertFrom-Json
        if (@($external.unexpectedExistingExternalDataOpens).Count -ne 0 -or
            @($external.networkAttempts).Count -ne 0 -or
            [int]$external.providerCalls -ne 0 -or
            [bool]$external.bronzeRowsOpened -or [bool]$external.sealedRowsOpened) {
            throw "External access invariant failed: $ExternalPath"
        }
    }
    if (-not (Test-Path -LiteralPath $IsolatedPath -PathType Leaf)) { throw "Missing isolated-data evidence: $IsolatedPath" }
    $isolated = Get-Content -Raw -LiteralPath $IsolatedPath | ConvertFrom-Json
    if ($isolated.schema -ne 'PHASE_7D5A2_ISOLATED_DATA_MANIFEST_V1' -or @($isolated.violations).Count -ne 0) {
        throw "Isolated-data violations present: $IsolatedPath"
    }
}

function Get-StatusCounts([object[]]$Results) {
    $counts = [ordered]@{ passed = 0; failed = 0; error = 0; skipped = 0; xfailed = 0; xpassed = 0 }
    foreach ($result in $Results) {
        $name = [string]$result.status
        if (-not $counts.Contains($name)) { throw "Unknown test status: $name" }
        $counts[$name] = [int]$counts[$name] + 1
    }
    return $counts
}

function Assert-SuiteResult(
    [string]$Name,
    [string]$CollectionPath,
    [string]$ExecutionCollectionPath,
    [string]$ExecutionPath,
    [string]$JunitPath,
    [int]$NativeExit,
    [object]$Expected,
    [string[]]$ExpectedFailed
) {
    foreach ($path in @($CollectionPath, $ExecutionCollectionPath, $ExecutionPath, $JunitPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "$Name evidence missing: $path" }
    }
    $collection = Get-Content -Raw -LiteralPath $CollectionPath | ConvertFrom-Json
    $executionCollection = Get-Content -Raw -LiteralPath $ExecutionCollectionPath | ConvertFrom-Json
    $execution = Get-Content -Raw -LiteralPath $ExecutionPath | ConvertFrom-Json
    $collected = @($collection.nodes)
    $recollected = @($executionCollection.nodes)
    $results = @($execution.results)
    $resultNodes = @($results | ForEach-Object { [string]$_.nodeId })
    if ($collection.schemaVersion -ne 'CODEX_PHASE7D5A7_COLLECTION_MANIFEST_V1' -or
        $execution.schemaVersion -ne 'CODEX_PHASE7D5A7_EXECUTION_MANIFEST_V1') { throw "$Name evidence schema mismatch" }
    if ($collected.Count -ne @($collected | Sort-Object -Unique).Count -or
        $recollected.Count -ne @($recollected | Sort-Object -Unique).Count -or
        $resultNodes.Count -ne @($resultNodes | Sort-Object -Unique).Count) { throw "$Name duplicate node identity" }
    $executionByNode = [Collections.Generic.Dictionary[string, object]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($result in $results) {
        $nodeId = [string]$result.nodeId
        if ([string]::IsNullOrWhiteSpace($nodeId)) { throw "$Name execution result has an empty node ID" }
        if ($executionByNode.ContainsKey($nodeId)) { throw "$Name duplicate exact execution node ID: $nodeId" }
        $executionByNode.Add($nodeId, $result)
    }
    if (($collected -join "`n") -ne ($recollected -join "`n") -or ($collected -join "`n") -ne ($resultNodes -join "`n")) {
        throw "$Name collection/execution mapping is not bijective"
    }
    if (@($execution.collectionErrors).Count -ne 0) { throw "$Name collection errors present" }
    $counts = Get-StatusCounts $results
    foreach ($field in @('passed', 'failed', 'error', 'skipped', 'xfailed', 'xpassed')) {
        $expectedField = if ($field -eq 'error') { 'errors' } else { $field }
        $expectedValue = [int]$Expected.$expectedField
        if ([int]$counts[$field] -ne $expectedValue) {
            throw "$Name status $field expected $expectedValue, got $($counts[$field])"
        }
    }
    if ($results.Count -ne [int]$Expected.collected) { throw "$Name collected expected $($Expected.collected), got $($results.Count)" }
    $actualFailed = @($results | Where-Object { $_.status -eq 'failed' } | ForEach-Object { [string]$_.nodeId } | Sort-Object)
    $expectedSorted = @($ExpectedFailed | Sort-Object)
    if (($actualFailed -join "`n") -ne ($expectedSorted -join "`n")) { throw "$Name failed-node partition changed" }
    $expectedNative = if ([int]$Expected.failed -eq 0) { 0 } else { 1 }
    if ($NativeExit -ne $expectedNative -or [int]$execution.exitStatus -ne $expectedNative) {
        throw "$Name native/plugin exit mismatch: native=$NativeExit manifest=$($execution.exitStatus) expected=$expectedNative"
    }
    [xml]$junit = Get-Content -Raw -LiteralPath $JunitPath
    $cases = @($junit.SelectNodes('//testcase'))
    $junitFailures = @($junit.SelectNodes('//testcase/failure')).Count
    $junitErrors = @($junit.SelectNodes('//testcase/error')).Count
    $junitSkipped = @($junit.SelectNodes('//testcase/skipped')).Count
    if ($cases.Count -ne $results.Count -or $junitFailures -ne [int]$counts.failed -or
        $junitErrors -ne [int]$counts.error -or $junitSkipped -ne 0) {
        throw "$Name JUnit aggregate is not identical to exact execution evidence"
    }
    $identitySeparator = [char]31
    $executionNodeByJunitIdentity = [Collections.Generic.Dictionary[string, string]]::new(
        [StringComparer]::Ordinal
    )
    $executionFileByNode = [Collections.Generic.Dictionary[string, string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($nodeId in $resultNodes) {
        $firstSeparator = $nodeId.IndexOf('::', [StringComparison]::Ordinal)
        if ($firstSeparator -le 0) { throw "$Name execution node ID has no file/item boundary: $nodeId" }
        $nodeFile = $nodeId.Substring(0, $firstSeparator).Replace('\', '/')
        if (-not $nodeFile.EndsWith('.py', [StringComparison]::Ordinal)) {
            throw "$Name execution node ID does not name a Python test file: $nodeId"
        }
        $itemHierarchy = @($nodeId.Substring($firstSeparator + 2) -split '::')
        if ($itemHierarchy.Count -eq 0 -or @($itemHierarchy | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -ne 0) {
            throw "$Name execution node ID has an invalid item hierarchy: $nodeId"
        }
        $testcaseName = [string]$itemHierarchy[-1]
        $className = $nodeFile.Substring(0, $nodeFile.Length - 3).Replace('/', '.')
        if ($itemHierarchy.Count -gt 1) {
            $className += '.' + (@($itemHierarchy[0..($itemHierarchy.Count - 2)]) -join '.')
        }
        if ($className.Contains($identitySeparator) -or $testcaseName.Contains($identitySeparator)) {
            throw "$Name execution identity contains the reserved separator: $nodeId"
        }
        $junitIdentity = $className + $identitySeparator + $testcaseName
        if ($executionNodeByJunitIdentity.ContainsKey($junitIdentity)) {
            throw (
                "$Name two execution node IDs collapse to one JUnit classname/name identity: " +
                "$($executionNodeByJunitIdentity[$junitIdentity]) and $nodeId"
            )
        }
        $executionNodeByJunitIdentity.Add($junitIdentity, $nodeId)
        $executionFileByNode.Add($nodeId, $nodeFile)
    }
    $seenJunitIdentities = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $junitByNode = [Collections.Generic.Dictionary[string, object]]::new([StringComparer]::Ordinal)
    $extraInJunit = @()
    foreach ($case in $cases) {
        $rawClassName = [string]$case.GetAttribute('classname')
        $rawFile = [string]$case.GetAttribute('file')
        $rawName = [string]$case.GetAttribute('name')
        if ([string]::IsNullOrWhiteSpace($rawClassName) -or [string]::IsNullOrWhiteSpace($rawName)) {
            throw "$Name JUnit testcase is missing its exact classname or name identity"
        }
        if ($rawClassName.Contains($identitySeparator) -or $rawName.Contains($identitySeparator)) {
            throw "$Name JUnit testcase contains the reserved identity separator"
        }
        $junitIdentity = $rawClassName + $identitySeparator + $rawName
        if (-not $seenJunitIdentities.Add($junitIdentity)) {
            throw "$Name duplicate exact JUnit classname/name identity: $rawClassName::$rawName"
        }
        if (-not $executionNodeByJunitIdentity.ContainsKey($junitIdentity)) {
            $extraInJunit += "$rawClassName::$rawName"
            continue
        }
        $junitNodeId = $executionNodeByJunitIdentity[$junitIdentity]
        if (-not [string]::IsNullOrWhiteSpace($rawFile)) {
            $normalizedFile = $rawFile.Replace('\', '/')
            if ($normalizedFile -ne $executionFileByNode[$junitNodeId]) {
                throw (
                    "$Name JUnit file disagrees with its exact execution node ID: " +
                    "$rawFile::$rawName -> $junitNodeId"
                )
            }
        }
        if ($junitByNode.ContainsKey($junitNodeId)) {
            throw "$Name multiple JUnit testcases map to one execution node ID: $junitNodeId"
        }
        $junitByNode.Add($junitNodeId, $case)
    }
    $missingFromJunit = @($resultNodes | Where-Object { -not $junitByNode.ContainsKey($_) })
    if ($missingFromJunit.Count -ne 0 -or $extraInJunit.Count -ne 0) {
        throw (
            "$Name JUnit/execution node-ID bijection failed; " +
            "missing=[$($missingFromJunit -join ', ')]; extra=[$($extraInJunit -join ', ')]"
        )
    }
    foreach ($nodeId in $resultNodes) {
        $case = $junitByNode[$nodeId]
        $failureCount = @($case.SelectNodes('./failure')).Count
        $errorCount = @($case.SelectNodes('./error')).Count
        $skippedCount = @($case.SelectNodes('./skipped')).Count
        if (($failureCount + $errorCount + $skippedCount) -gt 1) {
            throw "$Name JUnit testcase has mutually conflicting statuses: $nodeId"
        }
        $junitStatus = if ($failureCount -eq 1) {
            'failed'
        } elseif ($errorCount -eq 1) {
            'error'
        } elseif ($skippedCount -eq 1) {
            'skipped'
        } else {
            'passed'
        }
        $executionStatus = [string]$executionByNode[$nodeId].status
        if ($executionStatus -in @('xfailed', 'xpassed')) {
            throw "$Name xfail/xpass cannot be represented as an accepted JUnit result: $nodeId"
        }
        if ($junitStatus -ne $executionStatus) {
            throw "$Name JUnit/execution status mismatch for $nodeId`: junit=$junitStatus execution=$executionStatus"
        }
    }
    return [ordered]@{
        name = $Name
        collected = $results.Count
        passed = [int]$counts.passed
        failed = [int]$counts.failed
        errors = [int]$counts.error
        skipped = [int]$counts.skipped
        xfailed = [int]$counts.xfailed
        xpassed = [int]$counts.xpassed
        failedNodeIds = $actualFailed
    }
}

function Invoke-Suite(
    [string]$Name,
    [string]$SuiteRel,
    [string]$SuiteKind,
    [object]$Expected,
    [string[]]$ExpectedFailed,
    [string]$ParentRoot
) {
    $suiteRoot = Join-Path $ParentRoot $Name
    Assert-SafeMutablePath $suiteRoot $ParentRoot
    New-Item -ItemType Directory -Force -Path $suiteRoot | Out-Null

    $collectionRoot = Join-Path $suiteRoot 'collection'
    $executionRoot = Join-Path $suiteRoot 'execution'
    foreach ($phaseRoot in @($collectionRoot, $executionRoot)) {
        Assert-SafeMutablePath $phaseRoot $suiteRoot
        New-Item -ItemType Directory -Force -Path $phaseRoot | Out-Null
        Copy-Item -LiteralPath $IssuerCommitted -Destination (Join-Path $phaseRoot 'issuer-registry.json')
    }
    $issuerCommittedSha = (Get-FileHash -LiteralPath $IssuerCommitted -Algorithm SHA256).Hash.ToLowerInvariant()

    $collectionManifest = Join-Path $collectionRoot 'collection.json'
    $collectionExternal = Join-Path $collectionRoot 'external-access.json'
    $collectionIsolated = Join-Path $collectionRoot 'isolated-data.json'
    $collectionIssuer = Join-Path $collectionRoot 'issuer-registry.json'
    Set-PhaseEnvironment $collectionRoot $SuiteKind $collectionIssuer $collectionManifest '' $collectionExternal $collectionIsolated
    & $Python -B -m pytest -q --collect-only -p no:cacheprovider `
        -p tests.codex_phase7d5a7_contract.issuer_plugin `
        -p tests.codex_phase7d5a7_contract.result_plugin `
        --basetemp (Join-Path $collectionRoot 'pytest-basetemp') $SuiteRel
    $collectionExit = $LASTEXITCODE
    if ($collectionExit -ne 0) { throw "$Name collection failed with $collectionExit" }
    Assert-ExternalEvidence $collectionExternal $collectionIsolated ($SuiteKind -ne 'contract')

    $executionCollection = Join-Path $executionRoot 'collection.json'
    $executionManifest = Join-Path $executionRoot 'execution.json'
    $executionExternal = Join-Path $executionRoot 'external-access.json'
    $executionIsolated = Join-Path $executionRoot 'isolated-data.json'
    $junit = Join-Path $executionRoot 'junit.xml'
    $executionIssuer = Join-Path $executionRoot 'issuer-registry.json'
    Set-PhaseEnvironment $executionRoot $SuiteKind $executionIssuer $executionCollection $executionManifest $executionExternal $executionIsolated
    & $Python -B -m pytest -vv -ra --tb=short -p no:cacheprovider `
        -p tests.codex_phase7d5a7_contract.issuer_plugin `
        -p tests.codex_phase7d5a7_contract.result_plugin `
        --basetemp (Join-Path $executionRoot 'pytest-basetemp') `
        --junitxml $junit $SuiteRel
    $executionExit = $LASTEXITCODE
    Assert-ExternalEvidence $executionExternal $executionIsolated ($SuiteKind -ne 'contract')

    foreach ($issuer in @($collectionIssuer, $executionIssuer)) {
        if ((Get-FileHash -LiteralPath $issuer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $issuerCommittedSha) {
            throw "$Name issuer fixture changed"
        }
    }
    return Assert-SuiteResult $Name $collectionManifest $executionCollection $executionManifest $junit `
        $executionExit $Expected $ExpectedFailed
}

Assert-GitState

$tempParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$auditRoot = Join-Path $tempParent ("asp-phase7d5a7-contract-gate-" + [Guid]::NewGuid().ToString('N'))
Assert-SafeMutablePath $auditRoot
New-Item -ItemType Directory -Path $auditRoot | Out-Null

$sharedRuntime = Join-Path $Repo '.runtime'
$beforeRuntime = Get-MetadataInventory $sharedRuntime
$contract = Get-Content -Raw -LiteralPath $ContractPath | ConvertFrom-Json
$originalExpected = $contract.baseAuthorities.currentProductionBaseline.originalPackage
$deltaExpected = $contract.baseAuthorities.currentProductionBaseline.deltaPackage
$contractExpected = $contract.baseAuthorities.currentProductionBaseline.contractPackage
$originalFailed = @($originalExpected.failedNodeIds)
$deltaManifest = Get-Content -Raw -LiteralPath $DeltaManifestPath | ConvertFrom-Json
$deltaFailed = @($deltaManifest.findings | ForEach-Object { @($_.expectedFailingNodeIds) })

$summary = $null
$caught = $null
$runtimeMismatch = $false
try {
    $results = @()
    $results += Invoke-Suite 'original' $OriginalSuite 'original' $originalExpected $originalFailed $auditRoot
    $results += Invoke-Suite 'delta' $DeltaSuite 'delta' $deltaExpected $deltaFailed $auditRoot
    $results += Invoke-Suite 'contract' $ContractSuite 'contract' $contractExpected @() $auditRoot
    $summary = [ordered]@{
        schemaVersion = 'CODEX_PHASE7D5A7_CONTRACT_GATE_SUMMARY_V1'
        branch = (Invoke-GitLines @('branch', '--show-current'))[0].Trim()
        head = (Invoke-GitLines @('rev-parse', 'HEAD'))[0].Trim()
        reconciliationBase = $ReconciliationBase
        auditRoot = $auditRoot
        results = $results
        satisfiability = [ordered]@{ beforeConflicts = 2; afterConflicts = 0 }
        persistentSilverCreated = 0
        bronzeRowsOpened = 0
        sealedRowsOpened = 0
        networkAttempts = 0
        remoteActions = 0
    }
} catch {
    $caught = $_
} finally {
    $afterRuntime = Get-MetadataInventory $sharedRuntime
    $beforeJson = $beforeRuntime | ConvertTo-Json -Depth 10 -Compress
    $afterJson = $afterRuntime | ConvertTo-Json -Depth 10 -Compress
    $runtimeMismatch = $beforeJson -ne $afterJson
    $inventoryEvidence = [ordered]@{ before = $beforeRuntime; after = $afterRuntime; identical = (-not $runtimeMismatch) }
    $inventoryEvidence | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $auditRoot 'shared-runtime-inventory.json') -Encoding utf8
}

if ($runtimeMismatch) { throw "Shared .runtime metadata inventory changed; evidence retained at $auditRoot" }
if ($null -ne $caught) { throw "Contract gate failed; evidence retained at $auditRoot`n$($caught.Exception.Message)" }

$summary.sharedRuntimeChanged = $false
$summary.productionChanges = 0
$summary.mainChanged = $false
$summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $auditRoot 'contract-gate-summary.json') -Encoding utf8

Assert-GitState
Write-Output "Phase 7D.5A.7 contract gate passed. Evidence retained: $auditRoot"
Write-Output 'PHASE_7D5A7_CODEX_ACCEPTANCE_CONTRACT_RECONCILED'
