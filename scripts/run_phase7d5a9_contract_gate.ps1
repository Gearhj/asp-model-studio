<#
.SYNOPSIS
Runs the Phase 7D.5A.9 protected-set reconciliation authority.

The original, delta, and contract packages run in separate fresh external
roots.  Current production is expected to leave D3, D7, and D8 intentionally
red; every other protected node must be green.  This runner changes no
production or governed runtime state.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedBranch = 'phase7d5a9-codex-protected-set-reconciliation'
$SourceHead = '21fa2e621ae12b38ccbf4053fd8b18b4119bc96d'
$ExpectedSourceParent = '2dcfaebacc182ae6e6d331f640ea242672802d7d'
$CodexAncestor = '4b06cef966a906bdcc026351f719e1978650f78e'
$ExpectedMain = '924db29511f93909f9d785855bfa056775443690'
$ContractAuthoringCommit = 'b33e3b81dfcd82e065bc0efb0e29cc63da1fef29'
$PreservedReport = 'docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md'
$PreservedReportSha256 = '72c5a70d12a61f04ffdebfb2d3a5a11b17236b29abd0d9d36fd035ddd12593a6'
$OriginalSuite = 'tests/codex_phase7d5a3_red_gate'
$DeltaSuite = 'tests/codex_phase7d5a5_delta_red_gate'
$LegacyContractSuite = 'tests/codex_phase7d5a7_contract'
$BoundaryContractSuite = 'tests/codex_phase7d5a9_contract'
$RunnerRel = 'scripts/run_phase7d5a9_contract_gate.ps1'
$AllowedPostSourceChanges = @(
    'tests/codex_phase7d5a7_contract/acceptance_contract.json',
    'tests/codex_phase7d5a7_contract/test_contract.py',
    'tests/codex_phase7d5a9_contract/',
    $RunnerRel
)

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Repo
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$ContractPath = Join-Path $Repo "$LegacyContractSuite\acceptance_contract.json"
$BoundaryReportPath = Join-Path $Repo "$BoundaryContractSuite\acceptance_boundary_report.json"
$IssuerCommitted = Join-Path $Repo "$LegacyContractSuite\canonical_synthetic_issuer_registry.json"

foreach ($required in @($Python, $ContractPath, $BoundaryReportPath, $IssuerCommitted)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required authority file is missing: $required"
    }
}

function Invoke-GitLines([string[]]$Arguments) {
    $lines = @(& git @Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed ($LASTEXITCODE)"
    }
    return $lines
}

function Test-Within([string]$Child, [string]$Parent) {
    $childFull = [IO.Path]::GetFullPath($Child).TrimEnd('\', '/')
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    return $childFull.Equals($parentFull, [StringComparison]::OrdinalIgnoreCase) -or
        $childFull.StartsWith(
            $parentFull + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )
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
        if (Test-Within $full $forbidden) {
            throw "Mutable path is under forbidden authority: $full"
        }
    }
    if ($Parent -and -not (Test-Within $full $Parent)) {
        throw "Mutable child escaped the audit root: $full"
    }
    Assert-NoExistingReparse $full
}

function Get-MetadataInventory([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return [ordered]@{
            exists = $false
            root = [IO.Path]::GetFullPath($Root)
            files = 0
            directories = 0
            bytes = 0
            sha256 = ''
        }
    }
    $resolved = (Resolve-Path -LiteralPath $Root).Path
    $items = @(
        Get-ChildItem -LiteralPath $resolved -Force -Recurse -ErrorAction Stop |
            Sort-Object FullName
    )
    $lines = foreach ($item in $items) {
        $relative = $item.FullName.Substring($resolved.Length).Replace('\', '/')
        if ($item.PSIsContainer) {
            "D|$relative|$($item.CreationTimeUtc.Ticks)|$($item.LastWriteTimeUtc.Ticks)|$([int]$item.Attributes)"
        } else {
            "F|$relative|$($item.Length)|$($item.CreationTimeUtc.Ticks)|$($item.LastWriteTimeUtc.Ticks)|$([int]$item.Attributes)"
        }
    }
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = [Convert]::ToHexString(
            $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes(($lines -join "`n")))
        ).ToLowerInvariant()
    } finally {
        $hasher.Dispose()
    }
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

function Get-CodeTreeInventory([string[]]$RelativeRoots) {
    $records = @()
    foreach ($relativeRoot in $RelativeRoots) {
        $rootPath = Join-Path $Repo $relativeRoot
        if (-not (Test-Path -LiteralPath $rootPath -PathType Container)) { continue }
        foreach ($file in @(
            Get-ChildItem -LiteralPath $rootPath -File -Force -Recurse -ErrorAction Stop |
                Sort-Object FullName
        )) {
            $relative = $file.FullName.Substring($Repo.Length + 1).Replace('\', '/')
            $records += "$relative|$($file.Length)|$((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
        }
    }
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = [Convert]::ToHexString(
            $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes(($records -join "`n")))
        ).ToLowerInvariant()
    } finally {
        $hasher.Dispose()
    }
    return [ordered]@{
        roots = $RelativeRoots
        files = $records.Count
        sha256 = $digest
        mode = 'RELATIVE_PATH_LENGTH_AND_FILE_SHA256'
    }
}

function Assert-GitState {
    $branch = (@(Invoke-GitLines @('branch', '--show-current')))[0].Trim()
    if ($branch -ne $ExpectedBranch) { throw "Expected branch $ExpectedBranch, got $branch" }
    if ((@(Invoke-GitLines @('rev-parse', 'main')))[0].Trim() -ne $ExpectedMain) {
        throw 'main moved'
    }
    if ((@(Invoke-GitLines @('rev-parse', "$SourceHead^")))[0].Trim() -ne $ExpectedSourceParent) {
        throw 'The Claude source commit no longer has the expected direct parent'
    }
    & git merge-base --is-ancestor $CodexAncestor $SourceHead
    if ($LASTEXITCODE -ne 0) { throw 'The required Codex reconciliation ancestor is missing' }
    & git merge-base --is-ancestor $SourceHead HEAD
    if ($LASTEXITCODE -ne 0) { throw 'HEAD is not descended from the verified Claude source HEAD' }

    $headParents = @((@(Invoke-GitLines @('rev-list', '--parents', '-n', '1', 'HEAD')))[0].Trim() -split '\s+')
    if ($headParents.Count -ne 2 -or $headParents[1] -ne $ContractAuthoringCommit) {
        throw 'Final gate HEAD must be a single-parent direct child of the contract-authoring commit'
    }
    $authoringParents = @(
        (@(Invoke-GitLines @('rev-list', '--parents', '-n', '1', $ContractAuthoringCommit)))[0].Trim() -split '\s+'
    )
    if ($authoringParents.Count -ne 2 -or $authoringParents[1] -ne $SourceHead) {
        throw 'The contract-authoring commit must be a single-parent direct child of the verified source HEAD'
    }

    foreach ($marker in @(
        '.git\MERGE_HEAD', '.git\rebase-merge', '.git\rebase-apply',
        '.git\CHERRY_PICK_HEAD', '.git\BISECT_LOG'
    )) {
        if (Test-Path -LiteralPath (Join-Path $Repo $marker)) {
            throw "Incomplete Git operation: $marker"
        }
    }

    $changed = @(Invoke-GitLines @('diff', '--name-only', "$SourceHead..HEAD"))
    foreach ($raw in $changed) {
        $path = $raw.Trim().Replace('\', '/')
        $allowed = $false
        foreach ($rule in $AllowedPostSourceChanges) {
            if ($rule.EndsWith('/') -and $path.StartsWith($rule, [StringComparison]::Ordinal)) {
                $allowed = $true
                break
            }
            if (-not $rule.EndsWith('/') -and $path -eq $rule) {
                $allowed = $true
                break
            }
        }
        if (-not $allowed) { throw "Unauthorized post-source change: $path" }
    }
    $productionChanges = @(Invoke-GitLines @(
        'diff', '--name-only', "$SourceHead..HEAD", '--', 'server', 'src', 'tools'
    ))
    if ($productionChanges.Count -ne 0) {
        throw "Phase 7D.5A.9 changed production: $($productionChanges -join ', ')"
    }
    $authoringChanges = @(
        Invoke-GitLines @('diff', '--name-only', "$SourceHead..$ContractAuthoringCommit") |
            ForEach-Object { $_.Trim().Replace('\', '/') }
    )
    $expectedAuthoringChanges = @(
        'tests/codex_phase7d5a7_contract/acceptance_contract.json',
        'tests/codex_phase7d5a7_contract/test_contract.py',
        'tests/codex_phase7d5a9_contract/__init__.py',
        'tests/codex_phase7d5a9_contract/acceptance_boundary_report.json',
        'tests/codex_phase7d5a9_contract/acceptance_boundary_report_schema.json',
        'tests/codex_phase7d5a9_contract/test_boundary_contract.py'
    ) | Sort-Object
    if ((@($authoringChanges | Sort-Object) -join "`n") -ne ($expectedAuthoringChanges -join "`n")) {
        throw 'The contract-authoring commit changed an unexpected path or omitted an authority file'
    }
    $runnerChanges = @(
        Invoke-GitLines @('diff', '--name-only', "$ContractAuthoringCommit..HEAD") |
            ForEach-Object { $_.Trim().Replace('\', '/') }
    )
    if ($runnerChanges.Count -ne 1 -or $runnerChanges[0] -ne $RunnerRel) {
        throw 'The final gate commit must change exactly the Phase 7D.5A.9 runner'
    }
    & git diff --exit-code $ContractAuthoringCommit -- `
        'tests/codex_phase7d5a7_contract/acceptance_contract.json' `
        'tests/codex_phase7d5a7_contract/test_contract.py' `
        $BoundaryContractSuite
    if ($LASTEXITCODE -ne 0) { throw 'Contract authority changed after its authoring commit' }
    & git diff --exit-code HEAD -- $RunnerRel
    if ($LASTEXITCODE -ne 0) { throw 'Runner worktree bytes differ from the final gate commit' }

    $status = @(Invoke-GitLines @('status', '--porcelain=v1', '--untracked-files=all'))
    foreach ($line in $status) {
        if ($line.Length -lt 4) { continue }
        $path = $line.Substring(3).Replace('\', '/')
        if ($line.Substring(0, 2) -eq '??' -and $path -eq $PreservedReport) { continue }
        throw "Unexpected worktree disposition: $line"
    }
    $reportPath = Join-Path $Repo $PreservedReport
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        throw 'The preserved report is missing'
    }
    $reportSha = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($reportSha -ne $PreservedReportSha256) { throw 'The preserved report bytes changed' }
    & git diff --check
    if ($LASTEXITCODE -ne 0) { throw 'git diff --check failed' }
}

function Clear-PhaseEnvironment {
    foreach ($name in @(
        'CODEX_PHASE7D5A3_AUDIT_ROOT', 'CODEX_PHASE7D5A5_AUDIT_ROOT',
        'CODEX_PHASE7D5A3_EXTERNAL_ACCESS_MANIFEST',
        'CODEX_PHASE7D5A5_EXTERNAL_ACCESS_MANIFEST',
        'CODEX_PHASE7D5A7_ACTIVE_SUITE_ROOT',
        'CODEX_PHASE7D5A7_COLLECTION_MANIFEST',
        'CODEX_PHASE7D5A7_EXECUTION_MANIFEST',
        'CODEX_PHASE7D5A7_ISSUER_REGISTRY', 'ASP_SOURCE_ISSUER_REGISTRY',
        'ASP_MODEL_STUDIO_RUNTIME_ROOT', 'ASP_REQUIRE_ISOLATED_RUNTIME',
        'ASP_MODEL_EXCHANGE_ROOT', 'ASP_ISOLATED_TEST_TEMP',
        'ASP_ISOLATED_DATA_MANIFEST', 'PYTEST_ADDOPTS'
    )) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
}

function Set-PhaseEnvironment(
    [string]$PhaseRoot,
    [string]$SuiteKind,
    [string]$IssuerPath,
    [string]$CollectionManifest,
    [string]$ExecutionManifest,
    [string]$ExternalManifest,
    [string]$IsolatedManifest,
    [string]$Basetemp
) {
    Clear-PhaseEnvironment
    $runtime = Join-Path $PhaseRoot 'runtime'
    $temp = Join-Path $PhaseRoot 'temp'
    $exchange = Join-Path $PhaseRoot 'model-exchange-disabled'
    foreach ($path in @($runtime, $temp, $exchange, $Basetemp)) {
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
    $env:CODEX_PHASE7D5A7_COLLECTION_MANIFEST = $CollectionManifest
    if ($ExecutionManifest) { $env:CODEX_PHASE7D5A7_EXECUTION_MANIFEST = $ExecutionManifest }
    $env:CODEX_PHASE7D5A7_ISSUER_REGISTRY = $IssuerPath
    $env:ASP_SOURCE_ISSUER_REGISTRY = $IssuerPath
    $env:ASP_MODEL_STUDIO_RUNTIME_ROOT = $runtime
    $env:ASP_REQUIRE_ISOLATED_RUNTIME = '1'
    $env:ASP_MODEL_EXCHANGE_ROOT = $exchange
    $env:ASP_ISOLATED_TEST_TEMP = $Basetemp
    $env:ASP_ISOLATED_DATA_MANIFEST = $IsolatedManifest
    $env:TEMP = $temp
    $env:TMP = $temp
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
}

function Invoke-PytestCapture([string[]]$Arguments, [string]$LogPath) {
    $output = @(& $Python @Arguments 2>&1)
    $nativeExit = $LASTEXITCODE
    $textLines = @($output | ForEach-Object { [string]$_ })
    Set-Content -LiteralPath $LogPath -Value $textLines -Encoding UTF8
    return [pscustomobject]@{ exitCode = [int]$nativeExit; log = $LogPath }
}

function Get-StatusCounts([object[]]$Results) {
    $counts = [ordered]@{
        passed = 0
        failed = 0
        error = 0
        skipped = 0
        xfailed = 0
        xpassed = 0
    }
    foreach ($result in $Results) {
        $status = [string]$result.status
        if (-not $counts.Contains($status)) { throw "Unknown pytest status: $status" }
        $counts[$status] = [int]$counts[$status] + 1
    }
    return $counts
}

function Assert-ExternalEvidence(
    [string]$ExternalManifest,
    [string]$IsolatedManifest,
    [bool]$RequireExternal
) {
    if ($RequireExternal) {
        if (-not (Test-Path -LiteralPath $ExternalManifest -PathType Leaf)) {
            throw "Missing external-access evidence: $ExternalManifest"
        }
        $external = Get-Content -Raw -LiteralPath $ExternalManifest | ConvertFrom-Json
        if (@($external.unexpectedExistingExternalDataOpens).Count -ne 0 -or
            @($external.networkAttempts).Count -ne 0 -or
            [int]$external.providerCalls -ne 0 -or
            [bool]$external.bronzeRowsOpened -or
            [bool]$external.sealedRowsOpened) {
            throw "External-access invariant failed: $ExternalManifest"
        }
    }
    if (-not (Test-Path -LiteralPath $IsolatedManifest -PathType Leaf)) {
        throw "Missing isolated-data evidence: $IsolatedManifest"
    }
    $isolated = Get-Content -Raw -LiteralPath $IsolatedManifest | ConvertFrom-Json
    if ($isolated.schema -ne 'PHASE_7D5A2_ISOLATED_DATA_MANIFEST_V1' -or
        @($isolated.violations).Count -ne 0) {
        throw "Isolated-data violations present: $IsolatedManifest"
    }
}

function Assert-SuiteEvidence(
    [string]$Name,
    [string]$CollectionPath,
    [string]$ExecutionCollectionPath,
    [string]$ExecutionPath,
    [string]$JunitPath,
    [int]$CollectionExit,
    [int]$ExecutionExit,
    [object]$Expected,
    [string[]]$ExpectedFailed,
    [string]$ExternalManifest,
    [string]$IsolatedManifest,
    [bool]$RequireExternal
) {
    foreach ($path in @($CollectionPath, $ExecutionCollectionPath, $ExecutionPath, $JunitPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "$Name evidence is missing: $path"
        }
    }
    if ($CollectionExit -ne 0) { throw "$Name collection failed with $CollectionExit" }

    $collection = Get-Content -Raw -LiteralPath $CollectionPath | ConvertFrom-Json
    $executionCollection = Get-Content -Raw -LiteralPath $ExecutionCollectionPath | ConvertFrom-Json
    $execution = Get-Content -Raw -LiteralPath $ExecutionPath | ConvertFrom-Json
    if ($collection.schemaVersion -ne 'CODEX_PHASE7D5A7_COLLECTION_MANIFEST_V1' -or
        $executionCollection.schemaVersion -ne 'CODEX_PHASE7D5A7_COLLECTION_MANIFEST_V1' -or
        $execution.schemaVersion -ne 'CODEX_PHASE7D5A7_EXECUTION_MANIFEST_V1') {
        throw "$Name evidence schema mismatch"
    }
    $collected = @($collection.nodes)
    $recollected = @($executionCollection.nodes)
    $results = @($execution.results)
    $resultNodes = @($results | ForEach-Object { [string]$_.nodeId })
    $executionByNode = [Collections.Generic.Dictionary[string, object]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($result in $results) {
        $nodeId = [string]$result.nodeId
        if ([string]::IsNullOrWhiteSpace($nodeId)) {
            throw "$Name execution result has an empty node ID"
        }
        if ($executionByNode.ContainsKey($nodeId)) {
            throw "$Name duplicate exact execution node ID: $nodeId"
        }
        $executionByNode.Add($nodeId, $result)
    }
    foreach ($nodes in @($collected, $recollected, $resultNodes)) {
        if ($nodes.Count -ne @($nodes | Sort-Object -Unique).Count) {
            throw "$Name contains duplicate exact node IDs"
        }
    }
    if (($collected -join "`n") -ne ($recollected -join "`n") -or
        ($collected -join "`n") -ne ($resultNodes -join "`n")) {
        throw "$Name collection/execution parity is not exact and bijective"
    }
    if (@($execution.collectionErrors).Count -ne 0) { throw "$Name collection errors are present" }

    $counts = Get-StatusCounts $results
    foreach ($field in @('passed', 'failed', 'error', 'skipped', 'xfailed', 'xpassed')) {
        $expectedField = if ($field -eq 'error') { 'errors' } else { $field }
        if ([int]$counts[$field] -ne [int]$Expected.$expectedField) {
            throw "$Name $field expected $($Expected.$expectedField), got $($counts[$field])"
        }
    }
    if ($results.Count -ne [int]$Expected.collected) {
        throw "$Name collected expected $($Expected.collected), got $($results.Count)"
    }
    $actualFailed = @(
        $results | Where-Object { $_.status -eq 'failed' } |
            ForEach-Object { [string]$_.nodeId } | Sort-Object
    )
    $expectedFailedSorted = @($ExpectedFailed | Sort-Object)
    if (($actualFailed -join "`n") -ne ($expectedFailedSorted -join "`n")) {
        throw "$Name failed-node partition changed"
    }
    $expectedNative = if ([int]$Expected.failed -eq 0) { 0 } else { 1 }
    if ($ExecutionExit -ne $expectedNative -or [int]$execution.exitStatus -ne $expectedNative) {
        throw "$Name exit status mismatch: native=$ExecutionExit manifest=$($execution.exitStatus) expected=$expectedNative"
    }

    [xml]$junit = Get-Content -Raw -LiteralPath $JunitPath
    $cases = @($junit.SelectNodes('//testcase'))
    if ($cases.Count -ne $results.Count -or
        @($junit.SelectNodes('//testcase/failure')).Count -ne [int]$counts.failed -or
        @($junit.SelectNodes('//testcase/error')).Count -ne [int]$counts.error -or
        @($junit.SelectNodes('//testcase/skipped')).Count -ne 0) {
        throw "$Name JUnit aggregate differs from exact execution evidence"
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
        if ($firstSeparator -le 0) {
            throw "$Name execution node ID has no file/item boundary: $nodeId"
        }
        $nodeFile = $nodeId.Substring(0, $firstSeparator).Replace('\', '/')
        if (-not $nodeFile.EndsWith('.py', [StringComparison]::Ordinal)) {
            throw "$Name execution node ID does not name a Python test file: $nodeId"
        }
        $itemHierarchy = @($nodeId.Substring($firstSeparator + 2) -split '::')
        if ($itemHierarchy.Count -eq 0 -or
            @($itemHierarchy | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -ne 0) {
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
        if ([string]::IsNullOrWhiteSpace($rawClassName) -or
            [string]::IsNullOrWhiteSpace($rawName)) {
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
                throw "$Name JUnit file disagrees with its exact execution node ID: $rawFile::$rawName"
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
            throw "$Name JUnit testcase has conflicting statuses: $nodeId"
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
            throw "$Name xfail/xpass cannot be an accepted JUnit result: $nodeId"
        }
        if ($junitStatus -ne $executionStatus) {
            throw "$Name JUnit/execution status mismatch for $nodeId`: junit=$junitStatus execution=$executionStatus"
        }
    }
    Assert-ExternalEvidence $ExternalManifest $IsolatedManifest $RequireExternal
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
    [string]$SuiteKind,
    [string[]]$SuitePaths,
    [object]$Expected,
    [string[]]$ExpectedFailed,
    [string]$AuditRoot,
    [string]$IssuerPath,
    [bool]$RequireExternal
) {
    $phaseRoot = Join-Path $AuditRoot $Name
    Assert-SafeMutablePath $phaseRoot $AuditRoot
    New-Item -ItemType Directory -Force -Path $phaseRoot | Out-Null
    $collectionPath = Join-Path $phaseRoot 'collection.json'
    $executionCollectionPath = Join-Path $phaseRoot 'execution-collection.json'
    $executionPath = Join-Path $phaseRoot 'execution.json'
    $junitPath = Join-Path $phaseRoot 'junit.xml'
    $collectionExternalPath = Join-Path $phaseRoot 'collection-external-access.json'
    $collectionIsolatedPath = Join-Path $phaseRoot 'collection-isolated-data.json'
    $executionExternalPath = Join-Path $phaseRoot 'execution-external-access.json'
    $executionIsolatedPath = Join-Path $phaseRoot 'execution-isolated-data.json'
    $collectionBasetemp = Join-Path $phaseRoot 'collection-basetemp'
    $executionBasetemp = Join-Path $phaseRoot 'execution-basetemp'

    Set-PhaseEnvironment `
        $phaseRoot $SuiteKind $IssuerPath $collectionPath '' $collectionExternalPath `
        $collectionIsolatedPath $collectionBasetemp
    $commonPlugins = @(
        '-p', 'no:cacheprovider',
        '-p', 'tests.codex_phase7d5a7_contract.issuer_plugin',
        '-p', 'tests.codex_phase7d5a7_contract.result_plugin'
    )
    $collectionArgs = @(
        '-B', '-m', 'pytest', '--collect-only', '-q'
    ) + $commonPlugins + @('--basetemp', $collectionBasetemp) + $SuitePaths
    $collectionRun = Invoke-PytestCapture $collectionArgs (Join-Path $phaseRoot 'collection-output.txt')

    Set-PhaseEnvironment `
        $phaseRoot $SuiteKind $IssuerPath $executionCollectionPath $executionPath `
        $executionExternalPath $executionIsolatedPath $executionBasetemp
    $executionArgs = @(
        '-B', '-m', 'pytest', '-q', '-ra'
    ) + $commonPlugins + @(
        '--basetemp', $executionBasetemp,
        '--junitxml', $junitPath
    ) + $SuitePaths
    $executionRun = Invoke-PytestCapture $executionArgs (Join-Path $phaseRoot 'execution-output.txt')

    $summary = Assert-SuiteEvidence `
        $Name $collectionPath $executionCollectionPath $executionPath $junitPath `
        $collectionRun.exitCode $executionRun.exitCode $Expected $ExpectedFailed `
        $executionExternalPath $executionIsolatedPath $RequireExternal
    Assert-ExternalEvidence $collectionExternalPath $collectionIsolatedPath $RequireExternal
    $summary['collectionLog'] = $collectionRun.log
    $summary['executionLog'] = $executionRun.log
    return $summary
}

Assert-GitState
$worktreeBefore = @(Invoke-GitLines @('status', '--porcelain=v1', '--untracked-files=all'))
$productionBefore = Get-CodeTreeInventory @('server', 'src', 'tools')

$systemTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$AuditRoot = Join-Path $systemTemp ("asp-phase7d5a9-gate-" + [Guid]::NewGuid().ToString('N'))
Assert-SafeMutablePath $AuditRoot
New-Item -ItemType Directory -Path $AuditRoot | Out-Null
$IssuerPath = Join-Path $AuditRoot 'canonical_synthetic_issuer_registry.json'
Copy-Item -LiteralPath $IssuerCommitted -Destination $IssuerPath
$issuerBefore = (Get-FileHash -LiteralPath $IssuerPath -Algorithm SHA256).Hash.ToLowerInvariant()

$sharedRuntime = Join-Path $Repo '.runtime'
$runtimeBefore = Get-MetadataInventory $sharedRuntime
$contract = Get-Content -Raw -LiteralPath $ContractPath | ConvertFrom-Json
$boundaryReport = Get-Content -Raw -LiteralPath $BoundaryReportPath | ConvertFrom-Json
if (@($boundaryReport.scientificConflictGroups).Count -ne 0 -or
    @($boundaryReport.mutabilityConflictGroups).Count -ne 0) {
    throw 'The V2 boundary report contains a contradiction'
}

$originalExpected = $contract.baseAuthorities.currentProductionBaseline.originalPackage
$deltaExpected = $contract.baseAuthorities.currentProductionBaseline.deltaPackage
$contractExpected = [pscustomobject]@{
    collected = 17
    passed = 17
    failed = 0
    errors = 0
    skipped = 0
    xfailed = 0
    xpassed = 0
}

$results = @()
$results += Invoke-Suite `
    'original' 'original' @($OriginalSuite) $originalExpected @() `
    $AuditRoot $IssuerPath $true
$results += Invoke-Suite `
    'delta' 'delta' @($DeltaSuite) $deltaExpected @($deltaExpected.failedNodeIds) `
    $AuditRoot $IssuerPath $true
$results += Invoke-Suite `
    'contract' 'contract' @($LegacyContractSuite, $BoundaryContractSuite) `
    $contractExpected @() $AuditRoot $IssuerPath $false

if ($results.Count -ne 3 -or
    ($results | ForEach-Object { $_.name }) -join '|' -ne 'original|delta|contract') {
    throw 'Suite result aggregation was polluted or reordered'
}
if ((Get-FileHash -LiteralPath $IssuerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $issuerBefore) {
    throw 'The runner-owned issuer fixture changed during execution'
}
$runtimeAfter = Get-MetadataInventory $sharedRuntime
if (($runtimeBefore | ConvertTo-Json -Compress) -ne ($runtimeAfter | ConvertTo-Json -Compress)) {
    throw 'Shared runtime metadata changed during the reconciliation gate'
}
$productionAfter = Get-CodeTreeInventory @('server', 'src', 'tools')
if (($productionBefore | ConvertTo-Json -Compress) -ne ($productionAfter | ConvertTo-Json -Compress)) {
    throw 'Production source bytes changed during the reconciliation gate'
}
Assert-GitState
$worktreeAfter = @(Invoke-GitLines @('status', '--porcelain=v1', '--untracked-files=all'))
if (($worktreeBefore -join "`n") -ne ($worktreeAfter -join "`n")) {
    throw 'Worktree disposition changed during the reconciliation gate'
}

Clear-PhaseEnvironment
$summary = [ordered]@{
    schemaVersion = 'CODEX_PHASE7D5A9_GATE_RESULT_V1'
    verdict = 'PHASE_7D5A9_CODEX_PROTECTED_SET_RECONCILED'
    repository = $Repo
    branch = (@(Invoke-GitLines @('branch', '--show-current')))[0].Trim()
    head = (@(Invoke-GitLines @('rev-parse', 'HEAD')))[0].Trim()
    sourceHead = $SourceHead
    main = $ExpectedMain
    auditRoot = $AuditRoot
    retained = $true
    suites = $results
    contract = [ordered]@{
        schemaVersion = $contract.schemaVersion
        policyVersion = $contract.policyVersion
        canonicalSha256 = $boundaryReport.contractSha256
        boundaryReportFileSha256 = (
            Get-FileHash -LiteralPath $BoundaryReportPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        scientificContradictoryGroups = @($boundaryReport.scientificConflictGroups).Count
        mutabilityContradictoryGroups = @($boundaryReport.mutabilityConflictGroups).Count
        editableImplementationTargets = @(
            $contract.editableImplementationTargets | ForEach-Object { $_.path }
        )
    }
    sharedRuntimeBefore = $runtimeBefore
    sharedRuntimeAfter = $runtimeAfter
    productionBefore = $productionBefore
    productionAfter = $productionAfter
    safety = [ordered]@{
        bronzeRowsOpened = $false
        realSilverCreated = $false
        sealedRowsOpened = $false
        sharedRuntimeChanged = $false
        productionFilesModifiedByGate = 0
        remoteActions = 0
        pushes = 0
    }
}
$summary | ConvertTo-Json -Depth 10
'PHASE_7D5A9_CODEX_PROTECTED_SET_RECONCILED'
