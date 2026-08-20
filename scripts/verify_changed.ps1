#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$ListOnly,
    [switch]$SkipPublishDryRun
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
        git -c core.quotePath=false diff --name-only
        git -c core.quotePath=false diff --cached --name-only
        git -c core.quotePath=false ls-files --others --exclude-standard
    ) | ForEach-Object { $_.Trim().Replace("\", "/") } |
        Where-Object { $_ } |
        Sort-Object -Unique
    $stagedFiles = @(git -c core.quotePath=false diff --cached --name-only)
    $hasStagedFiles = $stagedFiles.Count -gt 0

    $selected = [System.Collections.Generic.List[string]]::new()
    $skipped = [System.Collections.Generic.List[string]]::new()
    $notRun = [System.Collections.Generic.List[string]]::new()
    $pytestTargets = [System.Collections.Generic.List[string]]::new()
    $ruffTargets = [System.Collections.Generic.List[string]]::new()

    Add-Unique -List $selected -Value "git diff --check"

    $hasDocs = $false
    $hasRecognitionFlow = $false
    $hasRecognitionFront = $false
    $hasRecognitionHeading = $false
    $hasRecognitionCore = $false
    $hasRecognitionBroad = $false
    $hasEngine = $false
    $hasWeb = $false
    $hasConfiguration = $false
    $hasPipeline = $false
    $hasSdk = $false
    $hasStorage = $false
    $hasSecurity = $false
    $hasDocumentShared = $false
    $hasFrontendFormat = $false
    $hasFrontendWorker = $false
    $hasWpsTransaction = $false
    $hasWpsControlFormat = $false
    $hasWpsDiagnostics = $false
    $hasWpsLauncher = $false
    $hasWpsAccountStore = $false
    $hasWpsFormatProfile = $false
    $hasWpsReaderRoutes = $false
    $hasWpsHostBridge = $false
    $hasWpsMonitor = $false
    $hasWpsPythonBroad = $false
    $hasWpsNode = $false
    $hasReader = $false
    $hasRelease = $false
    $hasApplication = $false
    $hasWpsServer = $false
    $hasDeployment = $false

    foreach ($path in $changed) {
        if ($path -match '^(AGENTS\.md|apps/.+/AGENTS\.md|docs/|.*\.md$)') { $hasDocs = $true }
        if ($path -match '^src/docxtool/document/(importing|segmentation|normalization)/') { $hasRecognitionFlow = $true }
        if ($path -match '^src/docxtool/document/recognition/') {
            if ($path -match '/(front_matter|selection|opening_speech|signature)\.py$' -or $path -match '/context/front\.py$') {
                $hasRecognitionFront = $true
            }
            elseif ($path -match '/(numbering|colon)\.py$' -or
                $path -match '/context/numbering\.py$' -or
                $path -match '/providers/numbering\.py$') {
                $hasRecognitionHeading = $true
            }
            elseif ($path -match '/decoder\.py$' -or
                $path -match '/decoding/' -or
                $path -match '/(candidates|state)\.py$') {
                $hasRecognitionCore = $true
            }
            else {
                $hasRecognitionBroad = $true
            }
        }
        if ($path -match '^src/docxtool/document/(engine|letterhead_config\.py)' -or
            $path -match '^tests/test_(engine|letterhead|page_number|numbering)') { $hasEngine = $true }
        if ($path -match '^src/docxtool/document/configuration/') { $hasConfiguration = $true }
        if ($path -match '^src/docxtool/document/pipeline/') { $hasPipeline = $true }
        if ($path -match '^src/docxtool/sdk/') { $hasSdk = $true }
        if ($path -match '^src/docxtool/storage/') { $hasStorage = $true }
        if ($path -match '^src/docxtool/security/') { $hasSecurity = $true }
        if ($path -match '^src/docxtool/document/(models/|source_tape\.py$|effective_format\.py$)') { $hasDocumentShared = $true }
        if ($path -match '^src/docxtool/web/' -or $path -match '^tests/test_web_') { $hasWeb = $true }
        if ($path -eq 'resources/frontend/pages/index.html') { $hasFrontendFormat = $true }
        elseif ($path -eq 'resources/frontend/pages/_worker.js') { $hasFrontendWorker = $true }
        elseif ($path -match '^resources/frontend/pages/') {
            $hasFrontendFormat = $true
            $hasFrontendWorker = $true
        }
        if ($path -match '^src/docxtool/application/' -or $path -match '^tests/test_application_') { $hasApplication = $true }
        if ($path -match '^src/docxtool/wps_server/' -or $path -match '^tests/test_wps_server_') { $hasWpsServer = $true }
        if ($path -match '^docxtool/' -or $path -match '^tests/test_deployment_') {
            $hasDeployment = $true
            $hasRelease = $true
        }
        if ($path -match '^apps/wps/.*\.py$' -and $path -notmatch '^apps/wps/tests/') {
            if ($path -match '^apps/wps/control/(document_transaction\.py|transactions/)') { $hasWpsTransaction = $true }
            elseif ($path -match '^apps/wps/control/(server|format_current_document|recognize_document|add_letterhead)\.py$') {
                $hasWpsControlFormat = $true
                if ($path -match '/server\.py$') { $hasWpsHostBridge = $true }
            }
            elseif ($path -match '^apps/wps/control/logging_adapter\.py$') { $hasWpsDiagnostics = $true }
            elseif ($path -match '^apps/wps/control/host_bridge\.py$') { $hasWpsHostBridge = $true }
            elseif ($path -match '^apps/wps/control/monitor\.py$') { $hasWpsMonitor = $true }
            elseif ($path -match '^apps/wps/control/reader_routes\.py$') { $hasWpsReaderRoutes = $true }
            elseif ($path -match '^apps/wps/account_store\.py$') { $hasWpsAccountStore = $true }
            elseif ($path -match '^apps/wps/format_profile_store\.py$') { $hasWpsFormatProfile = $true }
            elseif ($path -match '^apps/wps/(main|desktop_runtime|login_window|windows_startup|launcher_auth|account_runtime|public_api)\.py$') { $hasWpsLauncher = $true }
            elseif ($path -notmatch '/__init__\.py$') { $hasWpsPythonBroad = $true }
        }
        if ($path -match '^apps/wps/.*\.(js|mjs|html|css|svg)$') { $hasWpsNode = $true }
        if ($path -match '^apps/reader/' -or $path -match '^tests/reader/') { $hasReader = $true }
        if ($path -match '^(\.github/|scripts/|pyproject\.toml$|requirements[^/]*$|apps/wps/(package|requirements|manifest|ribbon)|apps/wps/scripts/)') { $hasRelease = $true }

        $leafName = Split-Path -Path $path -Leaf
        if ($path -like '*.py' -and
            $path -notmatch '(^|/)(\.venv|venv|site-packages|generated)/' -and
            (Test-Path -LiteralPath $path -PathType Leaf)) {
            Add-Unique -List $ruffTargets -Value $path
        }
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
    if ($hasRecognitionFlow) {
        foreach ($target in @(
            "tests/test_recognition_decoder_basic.py",
            "tests/test_recognition_decoder_headings.py",
            "tests/test_recognition_decoder_front_roles.py",
            "tests/test_colon_structure.py",
            "tests/test_native_numbering.py",
            "tests/test_segment_boundaries.py",
            "tests/test_segmentation_pipeline.py",
            "tests/test_normalization_pipeline.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "recognition/segmentation focused pytest targets"
    }
    if ($hasRecognitionFront -or $hasRecognitionBroad) {
        foreach ($target in @(
            "tests/test_recognition_decoder_front_roles.py",
            "tests/test_recognition_front_matter.py",
            "tests/test_recognition_selection.py",
            "tests/test_recognition_opening_speech.py",
            "tests/test_recognition_signature.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "recognition front/role focused pytest targets"
    }
    if ($hasRecognitionHeading -or $hasRecognitionBroad) {
        foreach ($target in @(
            "tests/test_recognition_decoder_headings.py",
            "tests/test_recognition_numbering.py",
            "tests/test_native_numbering.py",
            "tests/test_colon_structure.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "recognition heading/numbering focused pytest targets"
    }
    if ($hasRecognitionCore -or $hasRecognitionBroad) {
        foreach ($target in @(
            "tests/test_recognition_decoder_basic.py",
            "tests/test_recognition_state.py",
            "tests/test_recognition_selection.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "recognition decoder-core focused pytest targets"
    }
    if ($hasRecognitionBroad) {
        Add-Unique -List $selected -Value "recognition shared-core route (BROAD_BY_DESIGN)"
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
    if ($hasConfiguration) {
        foreach ($target in @(
            "tests/test_config_driven_styles.py",
            "tests/test_core_feature_integration.py",
            "tests/test_processing_flags.py",
            "tests/test_style_config_features.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "configuration focused pytest targets"
    }
    if ($hasPipeline) {
        foreach ($target in @(
            "tests/test_processing_flags.py",
            "tests/test_core_feature_integration.py",
            "tests/test_importer_facade.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "document pipeline focused pytest targets"
    }
    if ($hasSdk) {
        foreach ($target in @(
            "tests/test_sdk.py",
            "tests/test_sdk_binding.py",
            "tests/test_sdk_contract_v1.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "SDK focused pytest targets"
    }
    if ($hasStorage) {
        if (Test-Path -LiteralPath "tests/test_database_storage.py" -PathType Leaf) {
            Add-Unique -List $pytestTargets -Value "tests/test_database_storage.py"
        }
        Add-Unique -List $selected -Value "storage focused pytest targets"
    }
    if ($hasSecurity) {
        foreach ($target in @(
            "tests/test_docx_integrity.py",
            "tests/test_server_upload_security.py",
            "tests/test_audit_hardening.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "security focused pytest targets"
    }
    if ($hasDocumentShared) {
        foreach ($target in @(
            "tests/test_document_structure.py",
            "tests/test_importer_heading_flow.py",
            "tests/test_core_feature_integration.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "shared document regression targets (BROAD_BY_DESIGN)"
    }
    if ($hasWeb) {
        Get-ChildItem tests -File -Filter "test_web_*.py" | ForEach-Object {
            Add-Unique -List $pytestTargets -Value $_.FullName.Replace("$repoRoot\", "").Replace("\", "/")
        }
        Add-Unique -List $selected -Value "web focused pytest targets"
    }
    if ($hasFrontendFormat) {
        Add-Unique -List $selected -Value "node --test tests/frontend-format-config.test.mjs"
    }
    if ($hasFrontendWorker) {
        Add-Unique -List $selected -Value "node --test tests/worker-routing.test.mjs"
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
    if ($hasDeployment) {
        foreach ($target in @(
            "tests/test_deployment_package.py",
            "tests/test_deployment_package_version.py",
            "tests/test_deployment_source_parity.py"
        )) {
            Add-Unique -List $pytestTargets -Value $target
        }
        Add-Unique -List $selected -Value "deployment package focused pytest targets"
    }
    if ($hasWpsTransaction -or $hasWpsPythonBroad) {
        Add-Unique -List $pytestTargets -Value "apps/wps/tests/test_wps_transactions.py"
        Add-Unique -List $selected -Value "WPS transaction focused pytest target"
    }
    if ($hasWpsControlFormat -or $hasWpsPythonBroad) {
        Add-Unique -List $pytestTargets -Value "apps/wps/tests/test_wps_control_format.py"
        Add-Unique -List $selected -Value "WPS control/format focused pytest target"
    }
    if ($hasWpsDiagnostics -or $hasWpsPythonBroad) {
        Add-Unique -List $pytestTargets -Value "apps/wps/tests/test_wps_diagnostics.py"
        Add-Unique -List $selected -Value "WPS diagnostics focused pytest target"
    }
    if ($hasWpsLauncher -or $hasWpsPythonBroad) {
        foreach ($target in @(
            "apps/wps/tests/test_wps_launcher.py",
            "apps/wps/tests/test_launcher_auth.py",
            "apps/wps/tests/test_startup_account_flow.py",
            "apps/wps/tests/test_login_window.py",
            "apps/wps/tests/test_windows_startup.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "WPS launcher/login focused pytest targets"
    }
    if ($hasWpsAccountStore -or $hasWpsPythonBroad) {
        foreach ($target in @(
            "apps/wps/tests/test_account_store.py",
            "apps/wps/tests/test_startup_account_flow.py"
        )) {
            if (Test-Path -LiteralPath $target -PathType Leaf) { Add-Unique -List $pytestTargets -Value $target }
        }
        Add-Unique -List $selected -Value "WPS account-store focused pytest targets"
    }
    if ($hasWpsFormatProfile -or $hasWpsPythonBroad) {
        Add-Unique -List $pytestTargets -Value "apps/wps/tests/test_format_profile_store.py"
        Add-Unique -List $selected -Value "WPS format-profile focused pytest target"
    }
    if ($hasWpsReaderRoutes -or $hasWpsPythonBroad) {
        Add-Unique -List $pytestTargets -Value "apps/wps/tests/test_reader_routes.py"
        Add-Unique -List $selected -Value "WPS reader-route focused pytest target"
    }
    if ($hasWpsHostBridge -or $hasWpsPythonBroad) {
        Add-Unique -List $pytestTargets -Value "apps/wps/tests/test_host_bridge.py"
        Add-Unique -List $selected -Value "WPS HostBridge focused pytest target"
    }
    if ($hasWpsMonitor -or $hasWpsPythonBroad) {
        Add-Unique -List $pytestTargets -Value "apps/wps/tests/test_command_monitor.py"
        Add-Unique -List $selected -Value "WPS monitor focused pytest target"
    }
    if ($hasWpsPythonBroad) {
        Add-Unique -List $selected -Value "WPS Python fallback route (BROAD_BY_DESIGN)"
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
        if ($hasStagedFiles -or $SkipPublishDryRun) {
            $reason = if ($hasStagedFiles) { "staged index is not empty" } else { "invoked by publish workflow" }
            Add-Unique -List $skipped -Value "publish_to_github.ps1 -DryRun ($reason)"
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
    if ($ruffTargets.Count -gt 0) {
        Add-Unique -List $selected -Value "ruff changed Python files"
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
    if ($ruffTargets.Count -gt 0) {
        Invoke-Checked $python (@("-m", "ruff", "check") + @($ruffTargets | Sort-Object -Unique))
    }
    if ($hasWpsNode) {
        if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "NODE_NOT_FOUND" }
        Invoke-Checked node @("--test", "apps/wps/tests/run-node-tests.mjs")
    }
    if ($hasFrontendFormat) {
        if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "NODE_NOT_FOUND" }
        Invoke-Checked node @("--test", "tests/frontend-format-config.test.mjs")
    }
    if ($hasFrontendWorker) {
        if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "NODE_NOT_FOUND" }
        Invoke-Checked node @("--test", "tests/worker-routing.test.mjs")
    }
    if ($hasRelease) {
        Invoke-Checked $python @(
            "-m", "pytest", "tests/test_architecture_docs.py", "tests/test_pages_proxy_packaging.py", "-q"
        )
        if (-not $hasStagedFiles -and -not $SkipPublishDryRun) {
            Invoke-Checked pwsh @(
                "-NoProfile", "-File", ".\scripts\publish_to_github.ps1", "-DryRun"
            )
        }
    }
}
finally {
    Pop-Location
}
