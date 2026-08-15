#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$ListOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Verification command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Add-Unique {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[string]]$List,
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    if (-not $List.Contains($Value)) {
        $List.Add($Value)
    }
}

Push-Location -LiteralPath $repoRoot
try {
    $changed = @(
        git diff --name-only
        git diff --cached --name-only
        git ls-files --others --exclude-standard
    ) | ForEach-Object { $_.Trim().Replace("\", "/") } |
        Where-Object { $_ } |
        Sort-Object -Unique
    $stagedFiles = @(git diff --cached --name-only)
    $hasStagedFiles = $stagedFiles.Count -gt 0

    $selected = [System.Collections.Generic.List[string]]::new()
    $skipped = [System.Collections.Generic.List[string]]::new()
    $notRun = [System.Collections.Generic.List[string]]::new()
    $pytestTargets = [System.Collections.Generic.List[string]]::new()

    Add-Unique -List $selected -Value "git diff --check"

    $hasDocs = $false
    $hasRecognition = $false
    $hasEngine = $false
    $hasWeb = $false
    $hasWpsPython = $false
    $hasWpsNode = $false
    $hasReader = $false
    $hasRelease = $false
    $hasApplication = $false
    $hasWpsServer = $false

    foreach ($path in $changed) {
        if ($path -match '^(AGENTS\.md|apps/.+/AGENTS\.md|docs/|.*\.md$)') { $hasDocs = $true }
        if ($path -match '^src/docxtool/document/(recognition|importing|segmentation|normalization)/' -or
            $path -match '^tests/test_(recognition|native_numbering|colon_structure|segment|segmentation)') { $hasRecognition = $true }
        if ($path -match '^src/docxtool/document/(engine|letterhead_config\.py)' -or
            $path -match '^tests/test_(engine|letterhead|page_number|numbering)') { $hasEngine = $true }
        if ($path -match '^src/docxtool/web/' -or $path -match '^tests/test_web_') { $hasWeb = $true }
        if ($path -match '^src/docxtool/application/' -or $path -match '^tests/test_application_') { $hasApplication = $true }
        if ($path -match '^src/docxtool/wps_server/' -or $path -match '^tests/test_wps_server_') { $hasWpsServer = $true }
        if ($path -match '^apps/wps/.*\.py$') { $hasWpsPython = $true }
        if ($path -match '^apps/wps/.*\.(js|mjs|html|css|svg)$') { $hasWpsNode = $true }
        if ($path -match '^apps/reader/' -or $path -match '^tests/reader/') { $hasReader = $true }
        if ($path -match '^(\.github/|scripts/|pyproject\.toml$|requirements[^/]*$|apps/wps/(package|requirements|manifest|ribbon)|apps/wps/scripts/)') { $hasRelease = $true }

        $leafName = Split-Path -Path $path -Leaf
        if ($path -match '^(tests|apps/wps/tests)/.*\.py$' -and
            $leafName -like 'test_*.py' -and
            (Test-Path -LiteralPath $path -PathType Leaf)) {
            Add-Unique -List $pytestTargets -Value $path
        }
    }

    if ($hasDocs) {
        Add-Unique -List $selected -Value "pytest tests/test_architecture_docs.py -q"
        Add-Unique -List $skipped -Value "full documentation link audit"
    }
    if ($hasRecognition) {
        foreach ($target in @(
            "tests/test_recognition_decoder_basic.py",
            "tests/test_recognition_decoder_headings.py",
            "tests/test_recognition_decoder_front_roles.py",
            "tests/test_colon_structure.py",
            "tests/test_native_numbering.py",
            "tests/test_segment_boundaries.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "recognition/segmentation focused pytest targets"
    }
    if ($hasEngine) {
        foreach ($target in @(
            "tests/test_letterhead_engine.py",
            "tests/test_page_number_engine.py",
            "tests/test_numbering_engine.py",
            "tests/test_engine_heading_spacing.py",
            "tests/test_engine_render_numbering.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "engine/letterhead/numbering focused pytest targets"
    }
    if ($hasWeb) {
        Get-ChildItem tests -File -Filter "test_web_*.py" | ForEach-Object {
            Add-Unique -List $pytestTargets -Value $_.FullName.Replace("$repoRoot\", "").Replace("\", "/")
        }
        Add-Unique -List $selected -Value "web focused pytest targets"
    }
    if ($hasApplication) {
        Add-Unique -List $pytestTargets -Value "tests/test_application_process_document.py"
        Add-Unique -List $selected -Value "application focused pytest target"
    }
    if ($hasWpsServer) {
        Get-ChildItem tests -File -Filter "test_wps_server_*.py" | ForEach-Object {
            Add-Unique -List $pytestTargets -Value $_.FullName.Replace("$repoRoot\", "").Replace("\", "/")
        }
        Add-Unique -List $selected -Value "WPS server focused pytest targets"
    }
    if ($hasWpsPython) {
        foreach ($target in @(
            "apps/wps/tests/test_wps_transactions.py",
            "apps/wps/tests/test_wps_control_format.py",
            "apps/wps/tests/test_wps_diagnostics.py",
            "apps/wps/tests/test_wps_launcher.py",
            "apps/wps/tests/test_host_bridge.py",
            "apps/wps/tests/test_launcher_auth.py",
            "apps/wps/tests/test_startup_account_flow.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "WPS Python focused pytest targets"
    }
    if ($hasReader) {
        foreach ($target in @(
            "tests/reader/test_reader_service.py",
            "tests/reader/test_reader_parser.py",
            "tests/reader/test_reader_paths.py",
            "tests/reader/test_reader_import_text.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "Reader focused pytest targets"
        $hasWpsNode = $true
    }
    if ($hasWpsNode) {
        Add-Unique -List $selected -Value "node --test apps/wps/tests/run-node-tests.mjs"
    }
    if ($hasRelease) {
        Add-Unique -List $selected -Value "pytest tests/test_architecture_docs.py tests/test_pages_proxy_packaging.py -q"
        if ($hasStagedFiles) {
            Add-Unique -List $skipped -Value "publish_to_github.ps1 -DryRun (staged index is not empty)"
        }
        else {
            Add-Unique -List $selected -Value "publish_to_github.ps1 -DryRun"
        }
    }

    foreach ($target in $pytestTargets) {
        if (-not $selected.Contains("pytest changed/focused Python targets -q")) {
            Add-Unique -List $selected -Value "pytest changed/focused Python targets -q"
        }
    }

    if ($changed.Count -eq 0) {
        $selected.Clear()
        Add-Unique -List $selected -Value "git diff --check"
        Add-Unique -List $skipped -Value "all focused tests (no changed files)"
    }

    Write-Output "SELECTED_CHECKS"
    $selected | ForEach-Object { Write-Output "- $_" }
    Write-Output "SKIPPED_CHECKS"
    if ($skipped.Count -eq 0) { Write-Output "- none" } else { $skipped | ForEach-Object { Write-Output "- $_" } }
    Write-Output "NOT_RUN"
    Add-Unique -List $notRun -Value "full pytest suite"
    Add-Unique -List $notRun -Value "apps/wps/scripts/verify.ps1"
    Add-Unique -List $notRun -Value "EXE build"
    Add-Unique -List $notRun -Value "REAL_WPS_SMOKE"
    $notRun | ForEach-Object { Write-Output "- $_" }

    if ($ListOnly) { return }

    Invoke-Checked git @("diff", "--check")
    if ($pytestTargets.Count -gt 0) {
        Invoke-Checked $python (@("-m", "pytest") + @($pytestTargets | Sort-Object -Unique) + @("-q"))
    }
    if ($hasWpsNode) {
        if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "NODE_NOT_FOUND" }
        Invoke-Checked node @("--test", "apps/wps/tests/run-node-tests.mjs")
    }
    if ($hasRelease) {
        Invoke-Checked $python @(
            "-m", "pytest", "tests/test_architecture_docs.py", "tests/test_pages_proxy_packaging.py", "-q"
        )
        if (-not $hasStagedFiles) {
            Invoke-Checked pwsh @(
                "-NoProfile", "-File", ".\scripts\publish_to_github.ps1", "-DryRun"
            )
        }
    }
}
finally {
    Pop-Location
}
