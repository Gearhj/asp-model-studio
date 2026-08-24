<#
.SYNOPSIS
Runs only the auditor-owned Phase 7D.5A.11 D3/D7/D8 final-red tests.

The committed bfeff81 baseline is expected to produce seventeen deliberate
assertion failures and one passing one-to-one D8 control. Every mutable path is
fresh and external to the repository, shared runtime, model exchange, and data
staging roots. Evidence is retained whether validation succeeds or fails.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedBranch = 'phase7d5a11-codex-final-three-red-gate'
$BaselineHead = 'bfeff81a8348580627ed115efbd018392b083b82'
$ExpectedBaselineParent = '0f83083c80ad94c7e92e804ad366cb43e31b6378'
$ExpectedMain = '924db29511f93909f9d785855bfa056775443690'
$SuiteRel = 'tests/codex_phase7d5a11_final_red_gate'
$RunnerRel = 'scripts/run_phase7d5a11_codex_final_red_gate.ps1'
$ManifestRel = "$SuiteRel/acceptance_manifest.json"
$PreservedReport = 'docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md'
$PreservedReportSha256 = '72c5a70d12a61f04ffdebfb2d3a5a11b17236b29abd0d9d36fd035ddd12593a6'
$AuthorizedCommitPaths = @(
    "$SuiteRel/__init__.py",
    "$SuiteRel/acceptance_manifest.json",
    "$SuiteRel/conftest.py",
    "$SuiteRel/childsite/sitecustomize.py",
    "$SuiteRel/result_plugin.py",
    "$SuiteRel/test_d3.py",
    "$SuiteRel/test_d7.py",
    "$SuiteRel/test_d8.py",
    $RunnerRel
)
$ProtectedAuthorityPaths = @(
    'tests/codex_phase7d5a3_red_gate',
    'tests/codex_phase7d5a5_delta_red_gate',
    'tests/codex_phase7d5a7_contract',
    'tests/codex_phase7d5a9_contract'
)
$EnvironmentNames = @(
    'CODEX_PHASE7D5A11_AUDIT_ROOT',
    'CODEX_PHASE7D5A11_ACTIVE_PHASE_ROOT',
    'CODEX_PHASE7D5A11_COLLECTION_MANIFEST',
    'CODEX_PHASE7D5A11_EXECUTION_MANIFEST',
    'CODEX_PHASE7D5A11_EXTERNAL_ACCESS_MANIFEST',
    'CODEX_PHASE7D5A11_CHILD_AUDIT_LOG',
    'CODEX_PHASE7D5A11_REPO_ROOT',
    'ASP_MODEL_STUDIO_RUNTIME_ROOT',
    'ASP_REQUIRE_ISOLATED_RUNTIME',
    'ASP_MODEL_EXCHANGE_ROOT',
    'ASP_ISOLATED_TEST_TEMP',
    'ASP_ISOLATED_SESSION_CAPABILITY',
    'ASP_ISOLATED_DATA_MANIFEST',
    'PYTHONDONTWRITEBYTECODE',
    'PYTHONPYCACHEPREFIX',
    'PYTEST_DISABLE_PLUGIN_AUTOLOAD',
    'PYTEST_ADDOPTS',
    'PYTHONPATH',
    'TEMP',
    'TMP'
)

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Repo
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$ManifestPath = Join-Path $Repo $ManifestRel
function Invoke-GitLines([string[]]$Arguments) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = 'git'
    $start.WorkingDirectory = $Repo
    $start.UseShellExecute = $false
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in $Arguments) { [void]$start.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        if (-not $process.Start()) { throw 'git process did not start' }
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "git $($Arguments -join ' ') failed ($($process.ExitCode)): $stderr"
        }
        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            throw "git $($Arguments -join ' ') emitted stderr: $stderr"
        }
        return @($stdout -split "`r?`n" | Where-Object { $_ -ne '' })
    } finally {
        $process.Dispose()
    }
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
        return [ordered]@{
            exists = $false
            root = [IO.Path]::GetFullPath($Root)
            files = 0
            directories = 0
            bytes = 0
            sha256 = ''
            mode = 'PATH_LENGTH_CREATION_MTIME_ATTRIBUTES_NO_CONTENT_READ'
        }
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
    $bytesForHash = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $digest = [Convert]::ToHexString($hasher.ComputeHash($bytesForHash)).ToLowerInvariant() }
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

function Get-ContentInventory([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return [ordered]@{ exists = $false; root = [IO.Path]::GetFullPath($Root); files = @() }
    }
    $resolved = (Resolve-Path -LiteralPath $Root).Path
    $files = @(
        Get-ChildItem -LiteralPath $resolved -Force -Recurse -File -ErrorAction Stop |
            Sort-Object FullName |
            ForEach-Object {
                [ordered]@{
                    path = $_.FullName.Substring($resolved.Length).Replace('\', '/')
                    bytes = $_.Length
                    sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                    attributes = [int]$_.Attributes
                    lastWriteTimeUtcTicks = $_.LastWriteTimeUtc.Ticks
                }
            }
    )
    return [ordered]@{ exists = $true; root = $resolved; files = $files }
}

function Get-StringSha256([string]$Value) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return [Convert]::ToHexString(
            $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))
        ).ToLowerInvariant()
    } finally {
        $hasher.Dispose()
    }
}

function Assert-GitState {
    if ((@(Invoke-GitLines @('branch', '--show-current')))[0].Trim() -ne $ExpectedBranch) {
        throw "Expected branch $ExpectedBranch"
    }
    if ((@(Invoke-GitLines @('rev-parse', 'main')))[0].Trim() -ne $ExpectedMain) { throw 'main moved' }
    $baselineParents = ((@(Invoke-GitLines @('rev-list', '--parents', '-n', '1', $BaselineHead)))[0].Trim() -split '\s+')
    if ($baselineParents.Count -ne 2 -or $baselineParents[1] -ne $ExpectedBaselineParent) {
        throw "Baseline ancestry differs from $BaselineHead <- $ExpectedBaselineParent"
    }
    $parents = ((@(Invoke-GitLines @('rev-list', '--parents', '-n', '1', 'HEAD')))[0].Trim() -split '\s+')
    if ($parents.Count -ne 2 -or $parents[1] -ne $BaselineHead) {
        throw "HEAD must be a single-parent direct child of $BaselineHead"
    }
    foreach ($marker in @(
        '.git\MERGE_HEAD', '.git\rebase-merge', '.git\rebase-apply', '.git\CHERRY_PICK_HEAD',
        '.git\REVERT_HEAD', '.git\BISECT_LOG', '.git\sequencer'
    )) {
        if (Test-Path -LiteralPath (Join-Path $Repo $marker)) { throw "Incomplete Git operation: $marker" }
    }
    $changed = @(
        Invoke-GitLines @('diff', '--name-only', "$BaselineHead..HEAD") |
            ForEach-Object { $_.Trim().Replace('\', '/') } |
            Where-Object { $_ }
    )
    $expected = @($AuthorizedCommitPaths | Sort-Object)
    if ((@($changed | Sort-Object) -join "`n") -ne ($expected -join "`n")) {
        throw "Committed path inventory differs from the authorized final-red paths: $($changed -join ', ')"
    }
    $protectedDiffArgs = @('diff', '--exit-code', $BaselineHead, '--') + @($ProtectedAuthorityPaths)
    [void](Invoke-GitLines $protectedDiffArgs)
    $status = @(Invoke-GitLines @('status', '--porcelain=v1', '--untracked-files=all'))
    foreach ($line in $status) {
        if ($line.Length -lt 4) { continue }
        $path = $line.Substring(3).Replace('\', '/')
        if ($line.Substring(0, 2) -eq '??' -and $path -eq $PreservedReport) { continue }
        throw "Unexpected worktree disposition: $line"
    }
    $reportPath = Join-Path $Repo $PreservedReport
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) { throw 'Preserved report is missing' }
    if ((Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $PreservedReportSha256) {
        throw 'Preserved report bytes changed'
    }
    $packageRoot = Join-Path $Repo $SuiteRel
    $bytecodeShadows = @(
        Get-ChildItem -LiteralPath $packageRoot -Force -Recurse -ErrorAction Stop |
            Where-Object { $_.Name -eq '__pycache__' -or $_.Extension -eq '.pyc' }
    )
    if ($bytecodeShadows.Count -ne 0) {
        throw "Ignored Python bytecode could shadow the acceptance package: $($bytecodeShadows.FullName -join ', ')"
    }
    [void](Invoke-GitLines @('diff', '--check'))
}

function Assert-AcceptanceManifest {
    $manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
    $rootKeys = @($manifest.PSObject.Properties.Name | Sort-Object)
    $expectedRootKeys = @('baselineHead', 'builderConstraints', 'findings', 'manifestVersion', 'schemaVersion', 'suiteId')
    if (($rootKeys -join '|') -ne (($expectedRootKeys | Sort-Object) -join '|')) { throw 'Manifest root schema is not exact' }
    if ($manifest.schemaVersion -ne 'CODEX_PHASE7D5A11_ACCEPTANCE_MANIFEST_V1' -or
        [int]$manifest.manifestVersion -ne 1 -or $manifest.baselineHead -ne $BaselineHead -or
        $manifest.suiteId -ne 'ASP_MODEL_STUDIO_PHASE_7D5A11_FINAL_D3_D7_D8_RED_GATE') {
        throw 'Manifest identity or baseline mismatch'
    }
    if (-not [bool]$manifest.builderConstraints.testsImmutableToBuilder -or
        -not [bool]$manifest.builderConstraints.runnerImmutableToBuilder) {
        throw 'Builder immutability flags must both be true'
    }
    $requiredProhibitions = @(
        'editing', 'deleting', 'renaming', 'weakening', 'skipping', 'xfailing',
        'bypassing', 'shadowing', 'intercepting', 'changing acceptance inputs'
    )
    $actualProhibitions = @($manifest.builderConstraints.prohibitedActions | ForEach-Object { [string]$_ })
    if ((@($actualProhibitions | Sort-Object) -join '|') -ne (($requiredProhibitions | Sort-Object) -join '|')) {
        throw 'Manifest prohibited-action inventory changed'
    }
    $expectedFindingIds = @(
        'D3_REGISTRY_AND_PREPUBLICATION_HANDLE_AUTHORITY',
        'D7_PROCESS_AND_LEAF_BOUND_SESSION_AUTHORITY',
        'D8_DUPLICATE_AND_ALIAS_SAFE_RESULT_PARITY'
    )
    $expectedNodes = @{
        'D3_REGISTRY_AND_PREPUBLICATION_HANDLE_AUTHORITY' = @(
            "$SuiteRel/test_d3.py::test_silver_registry_schema_and_identity_are_verified_before_lookup",
            "$SuiteRel/test_d3.py::test_registry_source_root_redirect_to_byte_identical_clone_is_rejected",
            "$SuiteRel/test_d3.py::test_registry_entry_key_and_manifest_identity_must_agree",
            "$SuiteRel/test_d3.py::test_public_verify_rejects_candidate_derived_duck_typed_expected_source",
            "$SuiteRel/test_d3.py::test_public_verify_rejects_unregistered_object_even_with_genuine_source_handle",
            "$SuiteRel/test_d3.py::test_prepublication_handle_is_typed_scoped_and_single_operation_only"
        )
        'D7_PROCESS_AND_LEAF_BOUND_SESSION_AUTHORITY' = @(
            "$SuiteRel/test_d7.py::test_marker_with_wrong_process_id_is_rejected",
            "$SuiteRel/test_d7.py::test_session_start_does_not_retain_untrusted_preexisting_capability",
            "$SuiteRel/test_d7.py::test_unrelated_temp_path_factory_cannot_rebind_active_session_authority",
            "$SuiteRel/test_d7.py::test_copying_valid_marker_bytes_to_sibling_does_not_authorize_sibling",
            "$SuiteRel/test_d7.py::test_child_process_requires_its_own_process_bound_session_issuance",
            "$SuiteRel/test_d7.py::test_marker_from_prior_session_cannot_authorize_new_session"
        )
        'D8_DUPLICATE_AND_ALIAS_SAFE_RESULT_PARITY' = @(
            "$SuiteRel/test_d8.py::test_exact_duplicate_junit_testcases_are_fatal",
            "$SuiteRel/test_d8.py::test_parameter_slash_and_dot_alias_is_not_treated_as_same_identity",
            "$SuiteRel/test_d8.py::test_file_and_class_identity_cannot_be_erased_by_canonicalization",
            "$SuiteRel/test_d8.py::test_duplicate_collected_node_identity_is_fatal",
            "$SuiteRel/test_d8.py::test_parity_rejects_nonunit_cardinality_before_set_comparison",
            "$SuiteRel/test_d8.py::test_valid_one_to_one_identity_mapping_still_passes"
        )
    }
    $expectedImplementationPaths = @{
        'D3_REGISTRY_AND_PREPUBLICATION_HANDLE_AUTHORITY' = @(
            'server/sports_modeling/silver_publish.py', 'server/sports_modeling/source_issuer.py'
        )
        'D7_PROCESS_AND_LEAF_BOUND_SESSION_AUTHORITY' = @(
            'tests/_isolated_data_guard.py', 'tests/conftest.py'
        )
        'D8_DUPLICATE_AND_ALIAS_SAFE_RESULT_PARITY' = @('scripts/phase7d5a_skip_governance.py')
    }
    $findings = @($manifest.findings)
    if ($findings.Count -ne 3 -or
        (@($findings.findingId | Sort-Object) -join '|') -ne (($expectedFindingIds | Sort-Object) -join '|')) {
        throw 'Manifest finding inventory changed'
    }
    $allNodes = @()
    $failedNodes = @()
    $passedNodes = @()
    $failureSignatures = @{}
    foreach ($finding in $findings) {
        $nodes = @($finding.pytestNodeIds | ForEach-Object { [string]$_ })
        $failed = @($finding.expectedFailingNodeIds | ForEach-Object { [string]$_ })
        $passed = @($finding.expectedPassingNodeIds | ForEach-Object { [string]$_ })
        if ($nodes.Count -ne 6 -or $nodes.Count -ne @($nodes | Sort-Object -Unique).Count) {
            throw "$($finding.findingId) must own six unique nodes"
        }
        if ((@($nodes | Sort-Object) -join "`n") -ne
            (@($expectedNodes[[string]$finding.findingId] | Sort-Object) -join "`n")) {
            throw "$($finding.findingId) exact mandated node inventory changed"
        }
        if ((@($failed + $passed | Sort-Object) -join "`n") -ne (@($nodes | Sort-Object) -join "`n")) {
            throw "$($finding.findingId) baseline partition does not cover its nodes exactly"
        }
        if ([string]::IsNullOrWhiteSpace([string]$finding.auditReproduction) -or
            [string]::IsNullOrWhiteSpace([string]$finding.expectedBaselineFailure) -or
            [string]::IsNullOrWhiteSpace([string]$finding.correctedRequiredBehavior) -or
            [string]::IsNullOrWhiteSpace([string]$finding.risk) -or
            [string]::IsNullOrWhiteSpace([string]$finding.expectedFailureSignature)) {
            throw "$($finding.findingId) has an empty required narrative field"
        }
        $signatureProperties = @($finding.expectedFailureSignatures.PSObject.Properties)
        $signatureNodes = @($signatureProperties | ForEach-Object { [string]$_.Name })
        if ((@($signatureNodes | Sort-Object) -join "`n") -ne (@($failed | Sort-Object) -join "`n")) {
            throw "$($finding.findingId) per-node failure signatures do not exactly cover its red nodes"
        }
        foreach ($property in $signatureProperties) {
            $value = [string]$property.Value
            if ([string]::IsNullOrWhiteSpace($value) -or
                -not $value.StartsWith(([string]$finding.findingId + ':'), [StringComparison]::Ordinal)) {
                throw "$($finding.findingId) has an invalid node-specific failure signature"
            }
            $failureSignatures[[string]$property.Name] = $value
        }
        $implementationPaths = @($finding.affectedImplementationPaths | ForEach-Object { [string]$_ })
        if ((@($implementationPaths | Sort-Object) -join "`n") -ne
            (@($expectedImplementationPaths[[string]$finding.findingId] | Sort-Object) -join "`n")) {
            throw "$($finding.findingId) implementation-boundary inventory changed"
        }
        $expectedSubprocess = ([string]$finding.findingId -ne 'D3_REGISTRY_AND_PREPUBLICATION_HANDLE_AUTHORITY')
        if ([bool]$finding.subprocessRequired -ne $expectedSubprocess -or [bool]$finding.windowsOnly) {
            throw "$($finding.findingId) subprocess/Windows classification changed"
        }
        $allNodes += $nodes
        $failedNodes += $failed
        $passedNodes += $passed
    }
    if ($allNodes.Count -ne 18 -or $allNodes.Count -ne @($allNodes | Sort-Object -Unique).Count -or
        $failedNodes.Count -ne 17 -or $passedNodes.Count -ne 1) {
        throw 'Manifest must define 18 unique nodes as exactly 17 red and 1 green'
    }
    return [ordered]@{
        manifest = $manifest
        allNodes = $allNodes
        failedNodes = $failedNodes
        passedNodes = $passedNodes
        failureSignatures = $failureSignatures
    }
}

function Set-PhaseEnvironment(
    [string]$PhaseRoot,
    [string]$CollectionManifest,
    [string]$ExecutionManifest,
    [string]$ExternalManifest,
    [string]$IsolatedManifest,
    [string]$BaseTemp
) {
    foreach ($name in $EnvironmentNames) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
    $runtime = Join-Path $PhaseRoot 'runtime'
    $temp = Join-Path $PhaseRoot 'temp'
    $exchange = Join-Path $PhaseRoot 'model-exchange-disabled'
    $pycache = Join-Path $PhaseRoot 'python-cache'
    foreach ($path in @($runtime, $temp, $exchange, $BaseTemp, $pycache)) {
        Assert-SafeMutablePath $path $PhaseRoot
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }
    $env:CODEX_PHASE7D5A11_AUDIT_ROOT = $PhaseRoot
    $env:CODEX_PHASE7D5A11_ACTIVE_PHASE_ROOT = $PhaseRoot
    $env:CODEX_PHASE7D5A11_COLLECTION_MANIFEST = $CollectionManifest
    if ($ExecutionManifest) { $env:CODEX_PHASE7D5A11_EXECUTION_MANIFEST = $ExecutionManifest }
    $env:CODEX_PHASE7D5A11_EXTERNAL_ACCESS_MANIFEST = $ExternalManifest
    $env:ASP_MODEL_STUDIO_RUNTIME_ROOT = $runtime
    $env:ASP_REQUIRE_ISOLATED_RUNTIME = '1'
    $env:ASP_MODEL_EXCHANGE_ROOT = $exchange
    $env:ASP_ISOLATED_TEST_TEMP = $BaseTemp
    $env:ASP_ISOLATED_DATA_MANIFEST = $IsolatedManifest
    $env:TEMP = $temp
    $env:TMP = $temp
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONPYCACHEPREFIX = $pycache
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
}

function Assert-IsolationEvidence(
    [string]$ExternalPath,
    [string]$IsolatedPath,
    [string]$PhaseRoot,
    [int]$ExpectedChildStarts
) {
    if (-not (Test-Path -LiteralPath $ExternalPath -PathType Leaf)) { throw "Missing external evidence: $ExternalPath" }
    if (-not (Test-Path -LiteralPath $IsolatedPath -PathType Leaf)) { throw "Missing isolated evidence: $IsolatedPath" }
    $external = Get-Content -Raw -LiteralPath $ExternalPath | ConvertFrom-Json
    $isolated = Get-Content -Raw -LiteralPath $IsolatedPath | ConvertFrom-Json
    if ($external.schemaVersion -ne 'CODEX_PHASE7D5A11_EXTERNAL_ACCESS_V1' -or
        [IO.Path]::GetFullPath([string]$external.auditRoot) -ne [IO.Path]::GetFullPath($PhaseRoot) -or
        @($external.unexpectedExternalDataAttempts).Count -ne 0 -or
        @($external.unexpectedExistingExternalDataOpens).Count -ne 0 -or
        @($external.childViolations).Count -ne 0 -or
        @($external.networkAttempts).Count -ne 0 -or
        @($external.childNetworkAttempts).Count -ne 0 -or
        [int]$external.childProcessStarts -ne $ExpectedChildStarts -or
        [int]$external.providerCalls -ne 0 -or
        [bool]$external.bronzeRowsOpened -or [bool]$external.sealedRowsOpened) {
        throw "External access invariant failed: $ExternalPath"
    }
    if ($isolated.schema -ne 'PHASE_7D5A2_ISOLATED_DATA_MANIFEST_V1' -or @($isolated.violations).Count -ne 0) {
        throw "Isolated-data invariant failed: $IsolatedPath"
    }
}

function Get-ExecutionJunitIdentity([string]$NodeId) {
    $separator = $NodeId.IndexOf('::', [StringComparison]::Ordinal)
    if ($separator -le 0) { throw "Execution node has no file/item boundary: $NodeId" }
    $file = $NodeId.Substring(0, $separator).Replace('\', '/')
    if (-not $file.EndsWith('.py', [StringComparison]::Ordinal)) {
        throw "Execution node does not name a Python test file: $NodeId"
    }
    $hierarchy = @($NodeId.Substring($separator + 2) -split '::')
    if ($hierarchy.Count -eq 0 -or @($hierarchy | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -ne 0) {
        throw "Execution node has an invalid item hierarchy: $NodeId"
    }
    $name = [string]$hierarchy[-1]
    $className = $file.Substring(0, $file.Length - 3).Replace('/', '.')
    if ($hierarchy.Count -gt 1) {
        $className += '.' + (@($hierarchy[0..($hierarchy.Count - 2)]) -join '.')
    }
    return [ordered]@{
        key = $className + [char]31 + $name
        className = $className
        name = $name
        file = $file
        nodeId = $NodeId
    }
}

function Assert-ResultEvidence(
    [object]$Authority,
    [string]$CollectionPath,
    [string]$ExecutionCollectionPath,
    [string]$ExecutionPath,
    [string]$JunitPath,
    [int]$NativeExit
) {
    foreach ($path in @($CollectionPath, $ExecutionCollectionPath, $ExecutionPath, $JunitPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing result evidence: $path" }
    }
    $collection = Get-Content -Raw -LiteralPath $CollectionPath | ConvertFrom-Json
    $executionCollection = Get-Content -Raw -LiteralPath $ExecutionCollectionPath | ConvertFrom-Json
    $execution = Get-Content -Raw -LiteralPath $ExecutionPath | ConvertFrom-Json
    if ($collection.schemaVersion -ne 'CODEX_PHASE7D5A11_COLLECTION_MANIFEST_V1' -or
        $executionCollection.schemaVersion -ne 'CODEX_PHASE7D5A11_COLLECTION_MANIFEST_V1' -or
        $execution.schemaVersion -ne 'CODEX_PHASE7D5A11_EXECUTION_MANIFEST_V1') {
        throw 'Collection/execution evidence schema mismatch'
    }
    $collected = @($collection.nodes | ForEach-Object { [string]$_ })
    $recollected = @($executionCollection.nodes | ForEach-Object { [string]$_ })
    $results = @($execution.results)
    $resultNodes = @($results | ForEach-Object { [string]$_.nodeId })
    if ($collected.Count -ne 18 -or $collected.Count -ne @($collected | Sort-Object -Unique).Count -or
        $recollected.Count -ne @($recollected | Sort-Object -Unique).Count -or
        $resultNodes.Count -ne @($resultNodes | Sort-Object -Unique).Count) {
        throw 'Exact node inventory is not 18 unique nodes'
    }
    if (($collected -join "`n") -ne ($recollected -join "`n") -or
        ($collected -join "`n") -ne ($resultNodes -join "`n")) {
        throw 'Collection and execution node inventories are not identical'
    }
    if ((@($collected | Sort-Object) -join "`n") -ne (@($Authority.allNodes | Sort-Object) -join "`n")) {
        throw 'Collected nodes differ from the immutable acceptance manifest'
    }
    if (@($execution.collectionErrors).Count -ne 0) { throw 'Collection errors are present' }
    if ($NativeExit -ne 1 -or [int]$execution.exitStatus -ne 1) {
        throw "Expected a clean red pytest exit 1, got native=$NativeExit manifest=$($execution.exitStatus)"
    }
    $findingByNode = @{}
    foreach ($finding in @($Authority.manifest.findings)) {
        foreach ($node in @($finding.pytestNodeIds)) { $findingByNode[[string]$node] = $finding }
    }
    $failureEvidence = @()
    foreach ($result in $results) {
        $node = [string]$result.nodeId
        $expectedFailed = $node -in @($Authority.failedNodes)
        $expectedStatus = if ($expectedFailed) { 'failed' } else { 'passed' }
        if ([string]$result.status -ne $expectedStatus) {
            throw "Unexpected status for $node`: expected=$expectedStatus actual=$($result.status)"
        }
        $setup = $result.phases.setup
        $call = $result.phases.call
        $teardown = $result.phases.teardown
        if ($null -eq $setup -or $null -eq $call -or $null -eq $teardown -or
            $setup.outcome -ne 'passed' -or $teardown.outcome -ne 'passed') {
            throw "Fixture/setup/teardown failure for $node"
        }
        if ($expectedFailed) {
            $finding = $findingByNode[$node]
            $signature = [string]$Authority.failureSignatures[$node]
            $longrepr = [string]$call.longrepr
            if ($call.outcome -ne 'failed' -or -not $longrepr.Contains($signature, [StringComparison]::Ordinal)) {
                throw "Failure for $node did not reach its documented boundary/signature"
            }
            $failureEvidence += [ordered]@{
                nodeId = $node
                findingId = [string]$finding.findingId
                signature = $signature
                callLongreprSha256 = Get-StringSha256 $longrepr
            }
        } elseif ($call.outcome -ne 'passed') {
            throw "Positive control did not pass in its call phase: $node"
        }
    }
    if ($failureEvidence.Count -ne 17) { throw 'Failure-signature evidence must contain exactly 17 nodes' }

    [xml]$junit = Get-Content -Raw -LiteralPath $JunitPath
    $cases = @($junit.SelectNodes('//testcase'))
    if ($cases.Count -ne 18 -or @($junit.SelectNodes('//testcase/failure')).Count -ne 17 -or
        @($junit.SelectNodes('//testcase/error')).Count -ne 0 -or
        @($junit.SelectNodes('//testcase/skipped')).Count -ne 0) {
        throw 'JUnit aggregate does not encode exactly 17 failures and 1 pass'
    }
    $executionByJunitIdentity = [Collections.Generic.Dictionary[string, object]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($node in $resultNodes) {
        $identity = Get-ExecutionJunitIdentity $node
        if ($executionByJunitIdentity.ContainsKey([string]$identity.key)) {
            throw "Two execution nodes collapse to one JUnit classname/name identity: $node"
        }
        $executionByJunitIdentity.Add([string]$identity.key, $identity)
    }
    $seenJunitIdentities = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $junitByNode = [Collections.Generic.Dictionary[string, object]]::new([StringComparer]::Ordinal)
    $extraJunit = @()
    foreach ($case in $cases) {
        $className = [string]$case.GetAttribute('classname')
        $name = [string]$case.GetAttribute('name')
        $rawFile = [string]$case.GetAttribute('file')
        if ([string]::IsNullOrWhiteSpace($className) -or [string]::IsNullOrWhiteSpace($name)) {
            throw 'JUnit testcase is missing exact classname or name identity'
        }
        if ($className.EndsWith('.test_d7', [StringComparison]::Ordinal) -and
            [regex]::IsMatch([string]$case.InnerText, '(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])')) {
            throw "D7 JUnit evidence disclosed a capability-shaped 64-hex value: $name"
        }
        $key = $className + [char]31 + $name
        if (-not $seenJunitIdentities.Add($key)) { throw "Duplicate exact JUnit identity: $className::$name" }
        if (-not $executionByJunitIdentity.ContainsKey($key)) {
            $extraJunit += "$className::$name"
            continue
        }
        $identity = $executionByJunitIdentity[$key]
        if (-not [string]::IsNullOrWhiteSpace($rawFile) -and
            $rawFile.Replace('\', '/') -ne [string]$identity.file) {
            throw "JUnit file disagrees with execution node $($identity.nodeId)"
        }
        if ($junitByNode.ContainsKey([string]$identity.nodeId)) {
            throw "Multiple JUnit cases map to execution node $($identity.nodeId)"
        }
        $junitByNode.Add([string]$identity.nodeId, $case)
    }
    $missingJunit = @($resultNodes | Where-Object { -not $junitByNode.ContainsKey($_) })
    if ($missingJunit.Count -ne 0 -or $extraJunit.Count -ne 0) {
        throw "JUnit/execution identity bijection failed; missing=[$($missingJunit -join ', ')]; extra=[$($extraJunit -join ', ')]"
    }
    foreach ($node in $resultNodes) {
        $case = $junitByNode[$node]
        $junitStatus = if (@($case.SelectNodes('./failure')).Count -eq 1) { 'failed' } else { 'passed' }
        $expectedStatus = if ($node -in @($Authority.failedNodes)) { 'failed' } else { 'passed' }
        if ($junitStatus -ne $expectedStatus) { throw "JUnit status mismatch for $node" }
    }
    return [ordered]@{
        collected = 18
        failed = 17
        passed = 1
        errors = 0
        skipped = 0
        xfailed = 0
        xpassed = 0
        failedNodeIds = @($Authority.failedNodes)
        passedNodeIds = @($Authority.passedNodes)
        failureSignatureEvidence = $failureEvidence
    }
}

$previousEnvironment = @{}
foreach ($name in $EnvironmentNames) {
    $item = Get-Item "Env:$name" -ErrorAction SilentlyContinue
    $previousEnvironment[$name] = if ($null -eq $item) { $null } else { [string]$item.Value }
}

$tempParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$auditRoot = Join-Path $tempParent ("asp-phase7d5a11-final-red-" + [Guid]::NewGuid().ToString('N'))
Assert-SafeMutablePath $auditRoot
New-Item -ItemType Directory -Path $auditRoot | Out-Null

$sharedRuntime = Join-Path $Repo '.runtime'
$pytestCache = Join-Path $Repo '.pytest_cache'
$beforeRuntime = $null
$beforePytestCache = $null
$afterRuntime = $null
$afterPytestCache = $null
$authority = $null
$caught = $null
$runtimeMismatch = $false
$pytestCacheMismatch = $false
$resultSummary = $null
try {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Missing Python: $Python" }
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw "Missing manifest: $ManifestPath" }
    Assert-GitState
    $authority = Assert-AcceptanceManifest
    $beforeRuntime = Get-MetadataInventory $sharedRuntime
    $beforePytestCache = Get-ContentInventory $pytestCache

    $collectionRoot = Join-Path $auditRoot 'collection'
    $executionRoot = Join-Path $auditRoot 'execution'
    foreach ($root in @($collectionRoot, $executionRoot)) {
        Assert-SafeMutablePath $root $auditRoot
        New-Item -ItemType Directory -Path $root | Out-Null
    }

    $collectionManifest = Join-Path $collectionRoot 'collection.json'
    $collectionExternal = Join-Path $collectionRoot 'external-access.json'
    $collectionIsolated = Join-Path $collectionRoot 'isolated-data.json'
    $collectionBaseTemp = Join-Path $collectionRoot 'pytest-basetemp'
    $collectionLog = Join-Path $collectionRoot 'pytest-output.txt'
    Set-PhaseEnvironment $collectionRoot $collectionManifest '' $collectionExternal $collectionIsolated $collectionBaseTemp
    $collectionOutput = @(& $Python -B -m pytest $SuiteRel --collect-only -vv -rs `
        -p no:cacheprovider -p tests.codex_phase7d5a11_final_red_gate.result_plugin `
        --basetemp $collectionBaseTemp 2>&1)
    $collectionExit = $LASTEXITCODE
    @($collectionOutput | ForEach-Object { [string]$_ }) | Set-Content -LiteralPath $collectionLog -Encoding utf8
    if ($collectionExit -ne 0) { throw "Collection failed with exit $collectionExit" }
    Assert-IsolationEvidence $collectionExternal $collectionIsolated $collectionRoot 0

    $executionCollection = Join-Path $executionRoot 'collection.json'
    $executionManifest = Join-Path $executionRoot 'execution.json'
    $executionExternal = Join-Path $executionRoot 'external-access.json'
    $executionIsolated = Join-Path $executionRoot 'isolated-data.json'
    $executionBaseTemp = Join-Path $executionRoot 'pytest-basetemp'
    $executionLog = Join-Path $executionRoot 'pytest-output.txt'
    $junit = Join-Path $executionRoot 'junit.xml'
    Set-PhaseEnvironment $executionRoot $executionCollection $executionManifest $executionExternal $executionIsolated $executionBaseTemp
    $executionOutput = @(& $Python -B -m pytest $SuiteRel -vv -rs -p no:cacheprovider `
        -p tests.codex_phase7d5a11_final_red_gate.result_plugin `
        --basetemp $executionBaseTemp --junitxml $junit 2>&1)
    $executionExit = $LASTEXITCODE
    @($executionOutput | ForEach-Object { [string]$_ }) | Set-Content -LiteralPath $executionLog -Encoding utf8
    Assert-IsolationEvidence $executionExternal $executionIsolated $executionRoot 10
    $resultSummary = Assert-ResultEvidence $authority $collectionManifest $executionCollection $executionManifest $junit $executionExit
    Assert-GitState
    $afterPytestCache = Get-ContentInventory $pytestCache
    $pytestCacheMismatch = (($beforePytestCache | ConvertTo-Json -Depth 10 -Compress) -ne
        ($afterPytestCache | ConvertTo-Json -Depth 10 -Compress))
    if ($pytestCacheMismatch) { throw 'Pre-existing .pytest_cache metadata changed' }
} catch {
    $caught = $_
} finally {
    if ($null -ne $beforeRuntime) {
        try {
            $afterRuntime = Get-MetadataInventory $sharedRuntime
            $runtimeMismatch = (($beforeRuntime | ConvertTo-Json -Depth 10 -Compress) -ne
                ($afterRuntime | ConvertTo-Json -Depth 10 -Compress))
        } catch {
            $runtimeMismatch = $true
            if ($null -eq $caught) { $caught = $_ }
        }
    }
    if ($null -ne $beforePytestCache -and $null -eq $afterPytestCache) {
        try {
            $afterPytestCache = Get-ContentInventory $pytestCache
            $pytestCacheMismatch = (($beforePytestCache | ConvertTo-Json -Depth 10 -Compress) -ne
                ($afterPytestCache | ConvertTo-Json -Depth 10 -Compress))
        } catch {
            $pytestCacheMismatch = $true
            if ($null -eq $caught) { $caught = $_ }
        }
    }
    [ordered]@{
        schemaVersion = 'CODEX_PHASE7D5A11_SHARED_RUNTIME_INVENTORY_V1'
        before = $beforeRuntime
        after = $afterRuntime
        identical = (-not $runtimeMismatch)
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $auditRoot 'shared-runtime-inventory.json') -Encoding utf8
    [ordered]@{
        schemaVersion = 'CODEX_PHASE7D5A11_PREEXISTING_PYTEST_CACHE_INVENTORY_V1'
        before = $beforePytestCache
        after = $afterPytestCache
        identical = (-not $pytestCacheMismatch)
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $auditRoot 'pytest-cache-inventory.json') -Encoding utf8
    foreach ($name in $EnvironmentNames) {
        $prior = $previousEnvironment[$name]
        if ($null -eq $prior) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
        else { Set-Item "Env:$name" $prior }
    }
    if ($null -ne $caught) {
        [ordered]@{
            schemaVersion = 'CODEX_PHASE7D5A11_FAILURE_V1'
            message = $caught.Exception.Message
            auditRoot = $auditRoot
            sharedRuntimeChanged = $runtimeMismatch
            pytestCacheChanged = $pytestCacheMismatch
        } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $auditRoot 'gate-failure.json') -Encoding utf8
    }
}

if ($runtimeMismatch) { throw "Shared .runtime metadata inventory changed; evidence retained at $auditRoot" }
if ($pytestCacheMismatch) { throw "Pre-existing .pytest_cache metadata changed; evidence retained at $auditRoot" }
if ($null -ne $caught) { throw "Phase 7D.5A.11 gate failed; evidence retained at $auditRoot`n$($caught.Exception.Message)" }

$summary = [ordered]@{
    schemaVersion = 'CODEX_PHASE7D5A11_FINAL_RED_GATE_SUMMARY_V1'
    branch = (@(Invoke-GitLines @('branch', '--show-current')))[0].Trim()
    head = (@(Invoke-GitLines @('rev-parse', 'HEAD')))[0].Trim()
    baselineHead = $BaselineHead
    auditRoot = $auditRoot
    result = $resultSummary
    collectionManifest = (Join-Path $auditRoot 'collection\collection.json')
    executionManifest = (Join-Path $auditRoot 'execution\execution.json')
    junit = (Join-Path $auditRoot 'execution\junit.xml')
    sharedRuntimeChanged = $false
    bronzeRowsOpened = 0
    sealedRowsOpened = 0
    networkAttempts = 0
    providerCalls = 0
    productionFilesModifiedByGate = 0
    remoteActions = 0
    evidenceRetained = $true
}
$summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $auditRoot 'final-red-gate-summary.json') -Encoding utf8

Write-Output "Phase 7D.5A.11 final-red gate validated. Evidence retained: $auditRoot"
Write-Output 'Expected baseline partition: 17 deliberate assertion failures, 1 positive control pass, 0 errors/skips.'
