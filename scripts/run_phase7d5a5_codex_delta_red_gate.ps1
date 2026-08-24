<#
.SYNOPSIS
Runs only the immutable Codex Phase 7D.5A.5 delta-red Silver suite.

On the unmodified 0ab232b production baseline, a clean nonzero pytest result
is required and validated against the committed acceptance manifest.  On a
descendant with production repairs, the same immutable suite must instead be
fully green.  All mutable state and evidence stay under a fresh external root.
#>
[CmdletBinding()]
param([switch]$KeepRoot)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedBranch = 'phase7d5a5-codex-delta-red-silver-gate'
$SourceHead = '0ab232bc6a13b157ecc44a1902403a8a9ba7be1d'
$OriginalCodexBaseline = '9835689616aeff17357f096caea90b039eadfe0a'
$ExpectedMain = '924db29511f93909f9d785855bfa056775443690'
$SuiteRel = 'tests/codex_phase7d5a5_delta_red_gate'
$RunnerRel = 'scripts/run_phase7d5a5_codex_delta_red_gate.ps1'
$OriginalSuiteRel = 'tests/codex_phase7d5a3_red_gate'
$OriginalRunnerRel = 'scripts/run_phase7d5a3_codex_red_gate.ps1'
$PreservedReport = 'docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md'
$ProductionBoundaries = @(
    'server/sports_modeling/silver_publish.py',
    'server/sports_modeling/silver_transform.py',
    'tests/_isolated_data_guard.py',
    'scripts/phase7d5a_skip_governance.py'
)

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Repo
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Required repository Python environment not found: $Python"
}

function Invoke-GitLines([string[]]$Arguments) {
    $value = @(& git @Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
    return $value
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
            throw "Mutable path is inside forbidden authority: $full"
        }
    }
    if ($AuditParent -and -not (Test-PathWithin $full $AuditParent)) {
        throw "Mutable child escapes disposable audit root: $full"
    }
    Assert-NoExistingReparseComponent $full
}

function Get-MetadataInventory([string]$InventoryRoot) {
    $resolved = (Resolve-Path -LiteralPath $InventoryRoot).Path
    $files = @(Get-ChildItem -LiteralPath $resolved -Recurse -File -Force -ErrorAction Stop | Sort-Object FullName)
    $dirs = @(Get-ChildItem -LiteralPath $resolved -Recurse -Directory -Force -ErrorAction Stop | Sort-Object FullName)
    $sha = [Security.Cryptography.SHA256]::Create()
    $fileText = ($files | ForEach-Object {
        $_.FullName.Substring($resolved.Length).Replace('\', '/') + '|' + $_.Length + '|' +
            $_.CreationTimeUtc.Ticks + '|' + $_.LastWriteTimeUtc.Ticks + '|' + [int]$_.Attributes
    }) -join "`n"
    $dirText = ($dirs | ForEach-Object {
        $_.FullName.Substring($resolved.Length).Replace('\', '/') + '|' +
            $_.CreationTimeUtc.Ticks + '|' + $_.LastWriteTimeUtc.Ticks + '|' + [int]$_.Attributes
    }) -join "`n"
    return [ordered]@{
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

function Assert-OriginalCodexAuthority {
    & git diff --exit-code $OriginalCodexBaseline -- $OriginalSuiteRel $OriginalRunnerRel
    if ($LASTEXITCODE -ne 0) { throw 'Original Codex acceptance authority changed' }
}

function Assert-DeltaAuthority {
    $authorityCommits = @(Invoke-GitLines @('log', '--diff-filter=A', '--format=%H', '--reverse', '--', $RunnerRel))
    if ($authorityCommits.Count -gt 0) {
        $authorityCommit = $authorityCommits[0].Trim()
        & git diff --exit-code $authorityCommit -- $SuiteRel $RunnerRel
        if ($LASTEXITCODE -ne 0) {
            throw "Delta acceptance authority changed after its authoring commit $authorityCommit"
        }
        & git diff --exit-code -- $SuiteRel $RunnerRel
        if ($LASTEXITCODE -ne 0) { throw 'Delta acceptance authority has worktree modifications' }
    }
}

function Assert-WorktreeDisposition {
    $lines = @(Invoke-GitLines @('status', '--porcelain=v1', '--untracked-files=all'))
    foreach ($line in $lines) {
        if ($line.Length -lt 4) { continue }
        $path = $line.Substring(3).Replace('\', '/')
        if ($path -eq $PreservedReport) {
            if ($line.Substring(0, 2) -ne '??') {
                throw "Preserved report disposition changed: $line"
            }
            continue
        }
        if ($path -eq $RunnerRel -or $path.StartsWith("$SuiteRel/", [StringComparison]::Ordinal)) {
            continue
        }
        throw "Unexpected uncommitted path present: $line"
    }
}

function Assert-AcceptanceManifest([string]$Path, [string[]]$CollectedNodes) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Acceptance manifest missing: $Path"
    }
    $manifest = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $expectedRoot = @(
        'baselineHead', 'builderConstraints', 'findings', 'manifestVersion', 'schemaVersion', 'suiteId'
    ) | Sort-Object
    if ((@($manifest.PSObject.Properties.Name | Sort-Object) -join '|') -ne ($expectedRoot -join '|')) {
        throw 'Acceptance manifest root schema is not exact'
    }
    if ($manifest.schemaVersion -ne 'CODEX_PHASE7D5A5_DELTA_ACCEPTANCE_MANIFEST_V1' -or
        $manifest.manifestVersion -ne 1 -or $manifest.baselineHead -ne $SourceHead -or
        $manifest.suiteId -ne 'ASP_MODEL_STUDIO_PHASE_7D5A5_DELTA_RED_SILVER_GATE') {
        throw 'Acceptance manifest identity/baseline mismatch'
    }
    $expectedFindingIds = @(
        'D1_PATH_INDEPENDENT_SEASON_AUTHORITY',
        'D2_CRYPTOGRAPHIC_ISSUER_AUTHORITY',
        'D3_OUTER_RELATIONAL_RECONSTRUCTION',
        'D6_PRE_IO_CONTAINMENT_ORDER',
        'D7_SESSION_BOUND_TEMP_AUTHORITY',
        'D8_INJECTIVE_COLLECTION_RESULT_PARITY'
    )
    $actualFindingIds = @($manifest.findings | ForEach-Object { $_.findingId })
    if (($actualFindingIds -join '|') -ne ($expectedFindingIds -join '|')) {
        throw 'Acceptance manifest finding IDs/order are not exact'
    }
    $findingFields = @(
        'affectedProductionBoundary', 'currentExpectedFailureBehavior', 'expectedFailingNodeIds',
        'expectedFailureSignature', 'expectedPassingNodeIds', 'findingId', 'pytestNodeIds',
        'requiredCorrectedBehavior', 'riskTypes', 'sourceAuditFinding', 'subprocessRequired', 'windowsOnly'
    ) | Sort-Object
    $allManifestNodes = @()
    foreach ($finding in $manifest.findings) {
        if ((@($finding.PSObject.Properties.Name | Sort-Object) -join '|') -ne ($findingFields -join '|')) {
            throw "Finding $($finding.findingId) does not match the strict schema"
        }
        foreach ($field in @(
            'affectedProductionBoundary', 'currentExpectedFailureBehavior', 'expectedFailureSignature',
            'findingId', 'requiredCorrectedBehavior', 'sourceAuditFinding'
        )) {
            if ($finding.$field -isnot [string] -or [string]::IsNullOrWhiteSpace($finding.$field)) {
                throw "Finding $($finding.findingId) field $field must be a nonempty string"
            }
        }
        if ($finding.windowsOnly -isnot [bool] -or $finding.subprocessRequired -isnot [bool]) {
            throw "Finding $($finding.findingId) platform/subprocess fields must be booleans"
        }
        $nodes = @($finding.pytestNodeIds)
        $red = @($finding.expectedFailingNodeIds)
        $green = @($finding.expectedPassingNodeIds)
        if ($nodes.Count -eq 0 -or $red.Count -eq 0) {
            throw "Finding $($finding.findingId) must bind nodes and at least one baseline failure"
        }
        if (@($nodes | Sort-Object -Unique).Count -ne $nodes.Count -or
            @($red | Where-Object { $green -contains $_ }).Count -ne 0 -or
            ((@($red + $green | Sort-Object) -join '|') -ne (@($nodes | Sort-Object) -join '|'))) {
            throw "Finding $($finding.findingId) baseline-status partition is invalid"
        }
        foreach ($node in $nodes) {
            if ($node -isnot [string] -or [string]::IsNullOrWhiteSpace($node) -or
                $CollectedNodes -notcontains [string]$node) {
                throw "Finding $($finding.findingId) binds an invalid/uncollected node: $node"
            }
        }
        $risks = @($finding.riskTypes)
        if ($risks.Count -eq 0 -or @($risks | Sort-Object -Unique).Count -ne $risks.Count) {
            throw "Finding $($finding.findingId) riskTypes must be unique/nonempty"
        }
        foreach ($risk in $risks) {
            if ($risk -notin @('scientific', 'filesystem', 'gate-authority')) {
                throw "Finding $($finding.findingId) has unknown risk type $risk"
            }
        }
        $allManifestNodes += $nodes
    }
    if (@($allManifestNodes | Sort-Object -Unique).Count -ne $allManifestNodes.Count -or
        ((@($allManifestNodes | Sort-Object) -join '|') -ne (@($CollectedNodes | Sort-Object) -join '|'))) {
        throw 'Acceptance manifest must cover every collected node exactly once'
    }
    $constraints = $manifest.builderConstraints
    $constraintFields = @('prohibitedActions', 'runnerImmutableToBuilder', 'testsImmutableToBuilder') | Sort-Object
    if ((@($constraints.PSObject.Properties.Name | Sort-Object) -join '|') -ne ($constraintFields -join '|')) {
        throw 'Builder constraints do not match the strict schema'
    }
    $requiredActions = @(
        'editing', 'deleting', 'renaming', 'weakening', 'skipping', 'xfailing', 'replacing',
        'bypassing', 'shadowing', 'intercepting', 'changing acceptance inputs'
    )
    if ((@($constraints.prohibitedActions | Sort-Object) -join '|') -ne (@($requiredActions | Sort-Object) -join '|') -or
        $constraints.testsImmutableToBuilder -isnot [bool] -or
        $constraints.runnerImmutableToBuilder -isnot [bool] -or
        -not $constraints.testsImmutableToBuilder -or -not $constraints.runnerImmutableToBuilder) {
        throw 'Builder immutability constraints are not exact/fail-closed'
    }
    return $manifest
}

function Assert-ExternalManifest([string]$Path, [string]$AuditRoot, [string]$RuntimeRoot) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "External-access manifest missing: $Path"
    }
    $report = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $expected = @(
        'attempts', 'auditRoot', 'bronzeRowsOpened', 'networkAttempts', 'providerCalls',
        'runtimeRoot', 'schemaVersion', 'sealedRowsOpened', 'unexpectedExistingExternalDataOpens'
    ) | Sort-Object
    if ((@($report.PSObject.Properties.Name | Sort-Object) -join '|') -ne ($expected -join '|') -or
        $report.schemaVersion -ne 'CODEX_PHASE7D5A5_EXTERNAL_ACCESS_V1' -or
        $report.auditRoot -ne $AuditRoot -or $report.runtimeRoot -ne $RuntimeRoot -or
        $report.bronzeRowsOpened -isnot [bool] -or $report.sealedRowsOpened -isnot [bool] -or
        @($report.unexpectedExistingExternalDataOpens).Count -ne 0 -or
        @($report.networkAttempts).Count -ne 0 -or $report.providerCalls -ne 0 -or
        $report.bronzeRowsOpened -or $report.sealedRowsOpened -or
        @($report.attempts | Where-Object { $_.classification -eq 'shared_runtime' }).Count -ne 0) {
        throw "External-access evidence is malformed or unsafe: $Path"
    }
}

$branch = ((Invoke-GitLines @('branch', '--show-current')) -join '').Trim()
if ($branch -ne $ExpectedBranch) { throw "Wrong branch: $branch (expected $ExpectedBranch)" }
$main = ((Invoke-GitLines @('rev-parse', 'main')) -join '').Trim()
if ($main -ne $ExpectedMain) { throw "main moved from $ExpectedMain" }
& git merge-base --is-ancestor $SourceHead HEAD
if ($LASTEXITCODE -ne 0) { throw "HEAD does not descend from required source $SourceHead" }
Assert-OriginalCodexAuthority
Assert-DeltaAuthority
Assert-WorktreeDisposition

& git diff --quiet $SourceHead -- @ProductionBoundaries
$productionDiffRc = $LASTEXITCODE
if ($productionDiffRc -gt 1) { throw 'Unable to determine whether production boundaries changed' }
$baselineMode = $productionDiffRc -eq 0

$AuditRoot = [IO.Path]::GetFullPath((
    Join-Path ([IO.Path]::GetTempPath()) ('codex-phase7d5a5-delta-red-' + [Guid]::NewGuid().ToString('N'))
))
$RuntimeRoot = Join-Path $AuditRoot 'runtime'
$TempRoot = Join-Path $AuditRoot 'temp'
$PytestRoot = Join-Path $TempRoot 'pytest'
$ModelExchangeRoot = Join-Path $AuditRoot 'model-exchange-disabled'
Assert-SafeExternalMutablePath $AuditRoot
foreach ($path in @($RuntimeRoot, $TempRoot, $PytestRoot, $ModelExchangeRoot)) {
    Assert-SafeExternalMutablePath $path $AuditRoot
}
foreach ($path in @($AuditRoot, $RuntimeRoot, $TempRoot, $PytestRoot, $ModelExchangeRoot)) {
    New-Item -ItemType Directory -Path $path -ErrorAction Stop | Out-Null
}

$SharedRuntime = Join-Path $Repo '.runtime'
$BeforePath = Join-Path $AuditRoot 'shared-runtime-before.json'
$AfterPath = Join-Path $AuditRoot 'shared-runtime-after.json'
$HarnessErrorPath = Join-Path $AuditRoot 'harness-error.txt'
$before = Get-MetadataInventory $SharedRuntime
$before | ConvertTo-Json | Set-Content -LiteralPath $BeforePath -Encoding utf8
$finalExitCode = 3
$runtimeSame = $false

try {
    $env:CODEX_PHASE7D5A5_AUDIT_ROOT = $AuditRoot
    $env:ASP_MODEL_STUDIO_RUNTIME_ROOT = $RuntimeRoot
    $env:ASP_REQUIRE_ISOLATED_RUNTIME = '1'
    $env:ASP_ISOLATED_TEST_TEMP = $PytestRoot
    $env:TEMP = $TempRoot
    $env:TMP = $TempRoot
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONPATH = $Repo
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
    $env:ASP_MODEL_EXCHANGE_ROOT = $ModelExchangeRoot
    Remove-Item Env:PYTEST_ADDOPTS -ErrorAction SilentlyContinue

    $CollectedPath = Join-Path $AuditRoot 'collected-nodes.txt'
    $CollectionManifest = Join-Path $AuditRoot 'external-access-collection.json'
    $ExecutionManifest = Join-Path $AuditRoot 'external-access-execution.json'
    $JunitPath = Join-Path $AuditRoot 'delta-red-junit.xml'
    $FailurePath = Join-Path $AuditRoot 'failure-signatures.json'
    $SummaryPath = Join-Path $AuditRoot 'runner-summary.json'
    $ManifestPath = Join-Path $Repo "$SuiteRel\acceptance_manifest.json"

    $env:CODEX_PHASE7D5A5_EXTERNAL_ACCESS_MANIFEST = $CollectionManifest
    & $Python -B -m pytest $SuiteRel --collect-only -q -p no:cacheprovider 2>&1 |
        Set-Content -LiteralPath $CollectedPath -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw 'Delta-red collection failed' }
    $collected = @(
        Get-Content -LiteralPath $CollectedPath |
            Where-Object { $_ -match '::' } |
            ForEach-Object { $_.Trim().Replace('\', '/') }
    )
    if ($collected.Count -eq 0 -or @($collected | Sort-Object -Unique).Count -ne $collected.Count) {
        throw 'Collected-node inventory is empty or contains duplicates'
    }
    $acceptance = Assert-AcceptanceManifest $ManifestPath $collected

    $env:CODEX_PHASE7D5A5_EXTERNAL_ACCESS_MANIFEST = $ExecutionManifest
    & $Python -B -m pytest $SuiteRel -vv -rs -p no:cacheprovider --basetemp $PytestRoot --junitxml $JunitPath
    $pytestRc = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath $JunitPath -PathType Leaf)) { throw 'JUnit report missing' }

    [xml]$junit = Get-Content -LiteralPath $JunitPath -Raw
    $cases = @($junit.SelectNodes('//testcase'))
    $signatures = @()
    foreach ($case in $cases) {
        $status = 'passed'
        $message = ''
        $failureNode = $case.SelectSingleNode('failure')
        $errorNode = $case.SelectSingleNode('error')
        $skippedNode = $case.SelectSingleNode('skipped')
        if ($null -ne $failureNode) {
            $status = 'failed'
            $message = ([string]$failureNode.GetAttribute('message')) + "`n" + ([string]$failureNode.InnerText)
        } elseif ($null -ne $errorNode) {
            $status = 'error'
            $message = ([string]$errorNode.GetAttribute('message')) + "`n" + ([string]$errorNode.InnerText)
        } elseif ($null -ne $skippedNode) {
            $status = 'skipped'
            $message = [string]$skippedNode.GetAttribute('message')
        }
        $name = [string]$case.GetAttribute('name')
        $file = ([string]$case.GetAttribute('file')).Replace('\', '/')
        $nodeId = if ($file) { "$file::$name" } else { '' }
        if (-not $nodeId -or $collected -notcontains $nodeId) {
            $matches = @($collected | Where-Object { $_.EndsWith("::$name", [StringComparison]::Ordinal) })
            if ($matches.Count -ne 1) {
                throw "JUnit node cannot be mapped exactly: classname=$($case.GetAttribute('classname')) name=$name"
            }
            $nodeId = $matches[0]
        }
        $signatures += [ordered]@{ nodeId = $nodeId; status = $status; message = $message }
    }
    $caseNodes = @($signatures | ForEach-Object { $_.nodeId })
    if ($cases.Count -ne $collected.Count -or @($caseNodes | Sort-Object -Unique).Count -ne $caseNodes.Count -or
        ((@($caseNodes | Sort-Object) -join '|') -ne (@($collected | Sort-Object) -join '|'))) {
        throw 'Collection/JUnit execution parity is not exact'
    }

    $failed = @($signatures | Where-Object { $_.status -eq 'failed' }).Count
    $passed = @($signatures | Where-Object { $_.status -eq 'passed' }).Count
    $errors = @($signatures | Where-Object { $_.status -eq 'error' }).Count
    $skipped = @($signatures | Where-Object { $_.status -eq 'skipped' }).Count
    if ($errors -ne 0 -or $skipped -ne 0) {
        throw "Delta suite has fixture/runtime errors or skips (errors=$errors skipped=$skipped)"
    }
    if ($baselineMode) {
        if ($pytestRc -ne 1 -or $failed -eq 0) {
            throw "0ab232b baseline is not a clean intentional red state (pytest=$pytestRc failed=$failed)"
        }
        foreach ($finding in $acceptance.findings) {
            foreach ($node in @($finding.expectedFailingNodeIds)) {
                $record = @($signatures | Where-Object { $_.nodeId -eq $node })
                if ($record.Count -ne 1 -or $record[0].status -ne 'failed' -or
                    $record[0].message -notlike "*$($finding.expectedFailureSignature)*") {
                    throw "Expected deliberate failure/signature missing for $node"
                }
            }
            foreach ($node in @($finding.expectedPassingNodeIds)) {
                $record = @($signatures | Where-Object { $_.nodeId -eq $node })
                if ($record.Count -ne 1 -or $record[0].status -ne 'passed') {
                    throw "Expected baseline control did not pass: $node"
                }
            }
        }
    } else {
        if ($pytestRc -ne 0 -or $failed -ne 0 -or $passed -ne $collected.Count) {
            throw "Production-repair descendant has not made the immutable delta suite green"
        }
    }

    $signatures | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $FailurePath -Encoding utf8
    Assert-ExternalManifest $CollectionManifest $AuditRoot $RuntimeRoot
    Assert-ExternalManifest $ExecutionManifest $AuditRoot $RuntimeRoot
    [ordered]@{
        schemaVersion = 'CODEX_PHASE7D5A5_RUNNER_SUMMARY_V1'
        sourceHead = $SourceHead
        head = ((Invoke-GitLines @('rev-parse', 'HEAD')) -join '').Trim()
        baselineMode = $baselineMode
        collected = $collected.Count
        passed = $passed
        failed = $failed
        errors = $errors
        skipped = $skipped
        pytestExitCode = $pytestRc
        junit = $JunitPath
        failureSignatures = $FailurePath
        externalAccessCollection = $CollectionManifest
        externalAccessExecution = $ExecutionManifest
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $SummaryPath -Encoding utf8
    $finalExitCode = 0
} catch {
    ($_ | Out-String) | Set-Content -LiteralPath $HarnessErrorPath -Encoding utf8
    Write-Error $_
    $finalExitCode = 3
} finally {
    try {
        $after = Get-MetadataInventory $SharedRuntime
        $after | ConvertTo-Json | Set-Content -LiteralPath $AfterPath -Encoding utf8
        $runtimeSame = (
            $before.files -eq $after.files -and $before.directories -eq $after.directories -and
            $before.bytes -eq $after.bytes -and
            $before.fileInventorySha256 -eq $after.fileInventorySha256 -and
            $before.directoryInventorySha256 -eq $after.directoryInventorySha256
        )
        if (-not $runtimeSame) {
            'Shared runtime inventory changed' | Set-Content -LiteralPath $HarnessErrorPath -Encoding utf8
            $finalExitCode = 4
        }
    } catch {
        ($_ | Out-String) | Set-Content -LiteralPath $HarnessErrorPath -Encoding utf8
        $finalExitCode = 4
    }
    Write-Host "Phase 7D.5A.5 delta evidence retained at: $AuditRoot"
    Write-Host "Shared runtime unchanged: $runtimeSame"
    if (-not $KeepRoot -and $finalExitCode -eq 0) {
        Write-Host 'Evidence is intentionally preserved even without -KeepRoot for this immutable red gate.'
    }
}

exit $finalExitCode
