#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Quick,
    [switch]$Verify,
    [string]$Repository = "git@github.com:7654321x/docxtool.git",
    [string]$Branch = "main",
    [string]$SourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path,
    [string]$CommitMessage = "Sync project files"
)

$ErrorActionPreference = "Stop"

if ($Quick -and $Verify) {
    throw "-Quick and -Verify cannot be used together. Choose one publish verification level."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Assert-RequiredFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string[]]$RelativePaths
    )

    foreach ($relative in $RelativePaths) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $relative) -PathType Leaf)) {
            throw "Required publish file is missing: $relative"
        }
    }
}

function Assert-CleanIndex {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    Push-Location -LiteralPath $Root
    try {
        $staged = @(git diff --cached --name-status)
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect the local Git index."
        }
        if ($staged) {
            throw "The local Git index already contains staged changes. Commit or unstage them before publishing."
        }
    }
    finally {
        Pop-Location
    }
}

function Assert-NoForbiddenFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string[]]$RelativePaths
    )

    $forbidden = $RelativePaths | Where-Object {
            $relative = $_.Replace("\", "/")
            if ($relative -match '^var/(data|logs|outputs|runtime)/\.gitkeep$') {
                return $false
            }
            if ($relative -eq '.env.example') {
                return $false
            }
            $relative -match '(^|/)\.env(\.|$)' -or
            $relative -match '\.(pem|key|db|sqlite|sqlite3|log|zip)$' -or
            $relative -match '\.docx$' -or
            $relative -match '(^|/)(__pycache__|logs|outputs|runtime|build|dist|tmp_wheels|\.venv|\.pytest_cache|\.ruff_cache|\.playwright-mcp)(/|$)'
        }

    if ($forbidden) {
        throw "Forbidden files found in publish allowlist:`n$($forbidden -join "`n")"
    }
}

$requiredFiles = @(
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "apps/wps/__init__.py",
    "apps/wps/AGENTS.md",
    "apps/wps/DocxToolWps.spec",
    "apps/wps/README.md",
    "apps/wps/account_runtime.py",
    "apps/wps/account_store.py",
    "apps/wps/desktop_runtime.py",
    "apps/wps/client-config.json",
    "apps/wps/control/__init__.py",
    "apps/wps/control/add_letterhead.py",
    "apps/wps/control/document_transaction.py",
    "apps/wps/control/format_current_document.py",
    "apps/wps/control/host_bridge.py",
    "apps/wps/control/logging_adapter.py",
    "apps/wps/control/monitor.py",
    "apps/wps/control/recognize_document.py",
    "apps/wps/control/reader_routes.py",
    "apps/wps/control/server.py",
    "apps/wps/control/transactions/__init__.py",
    "apps/wps/control/transactions/models.py",
    "apps/wps/control/transport/__init__.py",
    "apps/wps/control/transport/protocol.py",
    "apps/wps/host-runtime.js",
    "apps/wps/format_profile_store.py",
    "apps/wps/format-config.js",
    "apps/wps/format-settings.html",
    "apps/wps/format-settings.js",
    "apps/wps/format-settings.css",
    "apps/wps/images/taskpane.svg",
    "apps/wps/images/taskpane-icons.svg",
    "apps/wps/images/check.svg",
    "apps/wps/images/eye.svg",
    "apps/wps/images/eye-off.svg",
    "apps/wps/images/login-window.png",
    "apps/wps/images/user.svg",
    "apps/wps/index.html",
    "apps/wps/js/bootstrap-complete.js",
    "apps/wps/js/bootstrap-log.js",
    "apps/wps/js/ribbon.js",
    "apps/wps/main.js",
    "apps/wps/main.py",
    "apps/wps/manifest.xml",
    "apps/wps/login_window.py",
    "apps/wps/package-lock.json",
    "apps/wps/package.json",
    "apps/wps/public_api.py",
    "apps/wps/windows_startup.py",
    "apps/wps/requirements-build.txt",
    "apps/wps/ribbon.xml",
    "apps/wps/reader/reader-client.js",
    "apps/wps/reader/reader-ui.js",
    "apps/wps/reader/reader.css",
    "apps/wps/scripts/build-exe.ps1",
    "apps/wps/scripts/verify.ps1",
    "apps/wps/taskpane.html",
    "apps/wps/taskpane.js",
    "apps/wps/tests/test_wps_transactions.py",
    "apps/wps/tests/test_wps_control_format.py",
    "apps/wps/tests/test_wps_diagnostics.py",
    "apps/wps/tests/test_wps_launcher.py",
    "apps/wps/tests/support/__init__.py",
    "apps/wps/tests/support/wps_app_support.py",
    "tests/support/__init__.py",
    "tests/support/recognition_helpers.py",
    "tests/test_recognition_decoder_basic.py",
    "tests/test_recognition_decoder_headings.py",
    "tests/test_recognition_decoder_front_roles.py",
    "apps/wps/tests/test_add_letterhead.py",
    "apps/wps/tests/test_command_monitor.py",
    "apps/wps/tests/test_host_bridge.py",
    "apps/wps/tests/test_account_store.py",
    "apps/wps/tests/test_launcher_auth.py",
    "apps/wps/tests/test_login_window.py",
    "apps/wps/tests/test_windows_startup.py",
    "apps/wps/tests/test_reader_routes.py",
    "apps/wps/tests/test_format_profile_store.py",
    "apps/wps/tests/test_startup_account_flow.py",
    "apps/wps/tests/reader-ui.test.mjs",
    "apps/wps/tests/format-settings.test.mjs",
    "apps/wps/tests/host-runtime.test.mjs",
    "apps/wps/tests/taskpane-runtime.test.mjs",
    "apps/wps/tests/support/wps-runtime-harness.mjs",
    "apps/wps/tests/run-node-tests.mjs",
    "CHANGELOG.md",
    "WPS_SERVER_PRD.md",
    "WPS_SERVER_TECHNICAL_DESIGN.md",
    "WPS_READER_PRD.md",
    "apps/reader/__init__.py",
    "apps/reader/README.md",
    "apps/reader/AGENTS.md",
    "apps/reader/models.py",
    "apps/reader/paths.py",
    "apps/reader/storage.py",
    "apps/reader/import_text.py",
    "apps/reader/parser.py",
    "apps/reader/service.py",
    "docs/README.md",
    "docs/ARCHITECTURE.md",
    "docs/design/WPS_READER_UI_TECHNICAL_DESIGN.md",
    "docs/design/WPS_BUILTIN_STYLE_GALLERY_TECHNICAL_DESIGN.md",
    "docs/design/GIT_BASELINE_RELEASE_WORKFLOW.md",
    "docs/design/CODEX_WORKFLOW_OPTIMIZATION.md",
    "docs/design/wps-format-settings.md",
    "docs/WPS_REGRESSION_CHECKLIST.md",
    "docs/API.md",
    "docs/SDK.md",
    "docs/INTEGRATION_CONTRACT_V1.md",
    "docs/examples/sdk-contract-examples.md",
    "docs/HOST_TEXT_V1_GOLDEN.json",
    "docs/WPS_VALIDATION.md",
    "公文格式规范.md",
    "CONVENTIONS.md",
    "docs/DEPLOY.md",
    "docs/migration/README.md",
    "docs/migration/codex-workflow.md",
    "docs/migration/phase-a2-checklist.md",
    "docs/migration/phase-a2-looper-log.md",
    "docs/migration/phase-a3-final-looper-log.md",
    "docs/migration/phase-b0-manifest.json",
    "docs/migration/phase-b0-report.md",
    "docs/DOCX_REGRESSION_CHECKLIST.md",
    "README.md",
    "docs/RELEASE.md",
    "requirements.txt",
    "requirements.lock",
    "requirements-dev.lock",
    "run.sh",
    "run.ps1",
    "deploy/nginx-docxtool.conf",
    "pyproject.toml",
    "src/docxtool/resources/__init__.py",
    "src/docxtool/resources/config/default-format.json",
    "src/docxtool/resources/schemas/__init__.py",
    "src/docxtool/resources/schemas/sdk-manifest-v1.schema.json",
    "src/docxtool/resources/schemas/recognition-request-v1.schema.json",
    "src/docxtool/resources/schemas/recognition-plan-v1.schema.json",
    "src/docxtool/resources/schemas/host-snapshot-v1.schema.json",
    "src/docxtool/resources/schemas/recognition-binding-v1.schema.json",
    "src/docxtool/resources/schemas/validation-report-v1.schema.json",
    "src/docxtool/resources/schemas/host-snapshot-summary-v1.schema.json",
    "src/docxtool/resources/schemas/sdk-error-v1.schema.json",
    "pytest.ini",
    "ruff.toml",
    ".github/workflows/ci.yml",
    "server.py",
    "src/docxtool/application/__init__.py",
    "src/docxtool/application/process_document.py",
    "src/docxtool/__init__.py",
    "src/docxtool/__main__.py",
    "src/docxtool/version.py",
    "src/docxtool/env.py",
    "src/docxtool/paths.py",
    "src/docxtool/auth/__init__.py",
    "src/docxtool/auth/passwords.py",
    "src/docxtool/auth/service.py",
    "src/docxtool/sdk/__init__.py",
    "src/docxtool/sdk/binding.py",
    "src/docxtool/sdk/cli.py",
    "src/docxtool/sdk/constants.py",
    "src/docxtool/sdk/errors.py",
    "src/docxtool/sdk/manifest.py",
    "src/docxtool/sdk/models.py",
    "src/docxtool/sdk/recognition.py",
    "src/docxtool/sdk/validation.py",
    "src/docxtool/web/__init__.py",
    "src/docxtool/web/app.py",
    "src/docxtool/web/bootstrap.py",
    "src/docxtool/web/runtime_state.py",
    "src/docxtool/web/compatibility.py",
    "src/docxtool/web/hooks.py",
    "src/docxtool/web/handler.py",
    "src/docxtool/web/admin_access.py",
    "src/docxtool/web/admin_actions.py",
    "src/docxtool/web/admin_auth.py",
    "src/docxtool/web/admin_forms.py",
    "src/docxtool/web/admin_pages.py",
    "src/docxtool/web/admin_route_handlers.py",
    "src/docxtool/web/admin_session_routes.py",
    "src/docxtool/web/admin_workspace_page.py",
    "src/docxtool/web/anonymous_identity.py",
    "src/docxtool/web/auth_payloads.py",
    "src/docxtool/web/auth_route_handlers.py",
    "src/docxtool/web/client_ip.py",
    "src/docxtool/web/config.py",
    "src/docxtool/web/database_schema.py",
    "src/docxtool/web/file_api_auth.py",
    "src/docxtool/web/file_utils.py",
    "src/docxtool/web/format_request.py",
    "src/docxtool/web/frontend_pages.py",
    "src/docxtool/web/handler_dispatch.py",
    "src/docxtool/web/handler_lifecycle.py",
    "src/docxtool/web/handler_responses.py",
    "src/docxtool/web/health.py",
    "src/docxtool/web/health_route_handlers.py",
    "src/docxtool/web/log_redaction.py",
    "src/docxtool/web/maintenance.py",
    "src/docxtool/web/monitoring.py",
    "src/docxtool/web/monitor_dashboard_page.py",
    "src/docxtool/web/monitoring_pages.py",
    "src/docxtool/web/monitor_route_handlers.py",
    "src/docxtool/web/owner_migration.py",
    "src/docxtool/web/page_route_handlers.py",
    "src/docxtool/web/preset_config.py",
    "src/docxtool/web/preset_defaults.py",
    "src/docxtool/web/preset_route_handlers.py",
    "src/docxtool/web/preset_store.py",
    "src/docxtool/web/protected_route_handlers.py",
    "src/docxtool/web/rate_limits.py",
    "src/docxtool/web/request_utils.py",
    "src/docxtool/web/request_params.py",
    "src/docxtool/web/route_authorization.py",
    "src/docxtool/web/responses.py",
    "src/docxtool/web/routing.py",
    "src/docxtool/web/secrets.py",
    "src/docxtool/web/server_runtime.py",
    "src/docxtool/web/stream_io.py",
    "src/docxtool/web/task_cache.py",
    "src/docxtool/web/task_paths.py",
    "src/docxtool/web/task_queue.py",
    "src/docxtool/web/task_records.py",
    "src/docxtool/web/task_recovery.py",
    "src/docxtool/web/task_route_handlers.py",
    "src/docxtool/web/task_result.py",
    "src/docxtool/web/task_statistics.py",
    "src/docxtool/web/task_state.py",
    "src/docxtool/web/task_worker.py",
    "src/docxtool/web/upload_route_handlers.py",
    "src/docxtool/web/time_check.py",
    "src/docxtool/web/user_auth.py",
    "src/docxtool/wps_server/__init__.py",
    "src/docxtool/wps_server/admin.py",
    "src/docxtool/wps_server/admin_routes.py",
    "src/docxtool/wps_server/auth.py",
    "src/docxtool/wps_server/config.py",
    "src/docxtool/wps_server/database.py",
    "src/docxtool/wps_server/format_config.py",
    "src/docxtool/wps_server/route_handlers.py",
    "src/docxtool/wps_server/service.py",
    "src/docxtool/wps_server/validation.py",
    "src/docxtool/document/__init__.py",
    "src/docxtool/document/classifier.py",
    "src/docxtool/document/configuration/__init__.py",
    "src/docxtool/document/configuration/models.py",
    "src/docxtool/document/configuration/validation.py",
    "src/docxtool/document/diagnostics/__init__.py",
    "src/docxtool/document/diagnostics/logging.py",
    "src/docxtool/document/errors.py",
    "src/docxtool/document/importer.py",
    "src/docxtool/document/pipeline/__init__.py",
    "src/docxtool/document/pipeline/document_pipeline.py",
    "src/docxtool/document/pipeline/options.py",
    "src/docxtool/document/pipeline/paragraph_materialization.py",
    "src/docxtool/document/importing/__init__.py",
    "src/docxtool/document/importing/features.py",
    "src/docxtool/document/importing/images.py",
    "src/docxtool/document/importing/inline_tokens.py",
    "src/docxtool/document/importing/numbering.py",
    "src/docxtool/document/importing/physical_format.py",
    "src/docxtool/document/importing/reader.py",
    "src/docxtool/document/importing/relationships.py",
    "src/docxtool/document/importing/sections.py",
    "src/docxtool/document/effective_format.py",
    "src/docxtool/document/source_tape.py",
    "src/docxtool/document/models/__init__.py",
    "src/docxtool/document/models/document.py",
    "src/docxtool/document/models/paragraph.py",
    "src/docxtool/document/models/source.py",
    "src/docxtool/document/normalization/__init__.py",
    "src/docxtool/document/normalization/changes.py",
    "src/docxtool/document/normalization/dates.py",
    "src/docxtool/document/normalization/numbering.py",
    "src/docxtool/document/normalization/pipeline.py",
    "src/docxtool/document/normalization/responsibility.py",
    "src/docxtool/document/normalization/signature.py",
    "src/docxtool/document/normalization/tail.py",
    "src/docxtool/document/normalization/text.py",
    "src/docxtool/document/segmentation/__init__.py",
    "src/docxtool/document/segmentation/body_tail.py",
    "src/docxtool/document/segmentation/boundaries.py",
    "src/docxtool/document/segmentation/conservation.py",
    "src/docxtool/document/segmentation/partition.py",
    "src/docxtool/document/segmentation/pipeline.py",
    "src/docxtool/document/segmentation/source_locator.py",
    "src/docxtool/document/segmentation/soft_breaks.py",
    "src/docxtool/document/letterhead_config.py",
    "src/docxtool/document/role_shape.py",
    "src/docxtool/document/recognition/__init__.py",
    "src/docxtool/document/recognition/attachment.py",
    "src/docxtool/document/recognition/candidates.py",
    "src/docxtool/document/recognition/colon.py",
    "src/docxtool/document/recognition/compatibility.py",
    "src/docxtool/document/recognition/config.py",
    "src/docxtool/document/recognition/core_adapter.py",
    "src/docxtool/document/recognition/decoder.py",
    "src/docxtool/document/recognition/diagnostics.py",
    "src/docxtool/document/recognition/document_mode.py",
    "src/docxtool/document/recognition/features.py",
    "src/docxtool/document/recognition/front_matter.py",
    "src/docxtool/document/recognition/global_context.py",
    "src/docxtool/document/recognition/context/__init__.py",
    "src/docxtool/document/recognition/context/analyzer.py",
    "src/docxtool/document/recognition/context/front.py",
    "src/docxtool/document/recognition/context/model.py",
    "src/docxtool/document/recognition/context/numbering.py",
    "src/docxtool/document/recognition/context/tail.py",
    "src/docxtool/document/recognition/decoding/__init__.py",
    "src/docxtool/document/recognition/decoding/candidate_selection.py",
    "src/docxtool/document/recognition/decoding/model.py",
    "src/docxtool/document/recognition/decoding/pipeline.py",
    "src/docxtool/document/recognition/decoding/review.py",
    "src/docxtool/document/recognition/decoding/transitions.py",
    "src/docxtool/document/recognition/legacy/__init__.py",
    "src/docxtool/document/recognition/legacy/classifier.py",
    "src/docxtool/document/recognition/legacy/pipeline.py",
    "src/docxtool/document/recognition/legacy/scoring.py",
    "src/docxtool/document/recognition/metadata.py",
    "src/docxtool/document/recognition/model.py",
    "src/docxtool/document/recognition/numbering.py",
    "src/docxtool/document/recognition/opening_speech.py",
    "src/docxtool/document/recognition/providers/__init__.py",
    "src/docxtool/document/recognition/providers/base.py",
    "src/docxtool/document/recognition/providers/compatibility.py",
    "src/docxtool/document/recognition/providers/key_value.py",
    "src/docxtool/document/recognition/providers/numbering.py",
    "src/docxtool/document/recognition/providers/semantic.py",
    "src/docxtool/document/recognition/providers/structural.py",
    "src/docxtool/document/recognition/selection.py",
    "src/docxtool/document/recognition/signature.py",
    "src/docxtool/document/recognition/state.py",
    "src/docxtool/document/recognition/tail_structure.py",
    "src/docxtool/document/recognition/validators.py",
    "src/docxtool/document/recognition/version.py",
    "src/docxtool/document/style_config.py",
    "src/docxtool/document/analysis/__init__.py",
    "src/docxtool/document/analysis/document_structure.py",
    "src/docxtool/document/analysis/layout_policy.py",
    "src/docxtool/document/analysis/letterhead.py",
    "src/docxtool/document/text/__init__.py",
    "src/docxtool/document/text/punctuation.py",
    "src/docxtool/document/engine/__init__.py",
    "src/docxtool/document/engine/cleanup.py",
    "src/docxtool/document/engine/context_candidate.py",
    "src/docxtool/document/engine/core.py",
    "src/docxtool/document/engine/export_pipeline.py",
    "src/docxtool/document/engine/render_context.py",
    "src/docxtool/document/engine/special_items.py",
    "src/docxtool/document/engine/paragraph_renderer.py",
    "src/docxtool/document/engine/export_finalize.py",
    "src/docxtool/document/engine/document_structure.py",
    "src/docxtool/document/engine/header_footer.py",
    "src/docxtool/document/engine/heading_body_split.py",
    "src/docxtool/document/engine/inline.py",
    "src/docxtool/document/engine/inline_effects.py",
    "src/docxtool/document/engine/letterhead.py",
    "src/docxtool/document/engine/normal.py",
    "src/docxtool/document/engine/numbering.py",
    "src/docxtool/document/engine/page_number.py",
    "src/docxtool/document/engine/paragraph_format.py",
    "src/docxtool/document/engine/paragraph_styles.py",
    "src/docxtool/document/engine/preservation.py",
    "src/docxtool/document/engine/render_options.py",
    "src/docxtool/document/engine/render_text.py",
    "src/docxtool/document/engine/render_types.py",
    "src/docxtool/document/engine/render_numbering.py",
    "src/docxtool/document/engine/punctuation.py",
    "src/docxtool/document/engine/punctuation_docx.py",
    "src/docxtool/document/engine/sections.py",
    "src/docxtool/document/engine/signature_block.py",
    "src/docxtool/document/engine/structure_context.py",
    "src/docxtool/document/engine/style_catalog.py",
    "src/docxtool/document/engine/table.py",
    "src/docxtool/document/engine/typography.py",
    "src/docxtool/security/__init__.py",
    "src/docxtool/security/docx_integrity.py",
    "src/docxtool/security/docx_validator.py",
    "src/docxtool/security/external_relationships.py",
    "src/docxtool/storage/__init__.py",
    "src/docxtool/storage/database.py",
    "scripts/generate_secrets.py",
    "scripts/analyze_end_format.py",
    "scripts/analyze_letterhead_batch.py",
    "scripts/batch_test_docx.py",
    "scripts/benchmark_recognition.py",
    "scripts/compare_recognition_runs.py",
    "scripts/phase_a_equivalence_snapshot.py",
    "scripts/phase_a_web_contract_snapshot.py",
    "scripts/check_public_metadata.py",
    "scripts/generate_005_format_fixtures.py",
    "scripts/generate_wps_validation_fixtures.py",
    "scripts/normalize_correct_template_role_spacing.py",
    "scripts/migrate_legacy_database.ps1",
    "scripts/verify_changed.ps1",
    "scripts/publish_to_github.ps1",
    "resources/frontend/pages/index.html",
    "resources/frontend/pages/_worker.js",
    "var/data/.gitkeep",
    "var/logs/.gitkeep",
    "var/outputs/.gitkeep",
    "var/runtime/.gitkeep"
)

$testFiles = Get-ChildItem -LiteralPath (Join-Path $SourceRoot "tests") -File -Recurse |
    Where-Object { $_.Name -like "test_*.py" -or $_.Name -like "*.test.mjs" } |
    ForEach-Object { [System.IO.Path]::GetRelativePath($SourceRoot, $_.FullName).Replace("\", "/") }
$publishFiles = @($requiredFiles + $testFiles | Sort-Object -Unique)
$stagedByScript = $false
$commitCreated = $false

Write-Host "Source: $SourceRoot"
Write-Host "Repository: $Repository"
Write-Host "Branch: $Branch"
$verificationMode = if ($Verify) { "full" } else { "quick" }
Write-Host "Mode: $(if ($DryRun) { 'dry-run' } else { 'push' }) | Verification: $verificationMode"

Push-Location -LiteralPath $SourceRoot
try {
    $gitRoot = (git rev-parse --show-toplevel).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "SourceRoot is not a Git repository: $SourceRoot"
    }
    if (-not [System.IO.Path]::GetFullPath($gitRoot).Equals(
        [System.IO.Path]::GetFullPath($SourceRoot),
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "SourceRoot must be the local Git repository root: $gitRoot"
    }

    $currentBranch = (git branch --show-current).Trim()
    if ($currentBranch -ne $Branch) {
        throw "Local branch mismatch: expected=$Branch actual=$currentBranch"
    }

    $pushUrl = (git remote get-url --push origin).Trim()
    if ($LASTEXITCODE -ne 0 -or $pushUrl -notmatch '^git@github\.com:') {
        throw "The origin push URL must use GitHub SSH before publishing: $pushUrl"
    }
    if ($Repository -notmatch '^git@github\.com:') {
        throw "Repository must use a GitHub SSH URL: $Repository"
    }

    Assert-CleanIndex -Root $SourceRoot
    Assert-RequiredFiles -Root $SourceRoot -RelativePaths $publishFiles
    Assert-NoForbiddenFiles -Root $SourceRoot -RelativePaths $publishFiles

    Invoke-Checked git @("fetch", "origin", $Branch)
    $initialRemote = (git rev-parse "origin/$Branch").Trim()
    $initialLocal = (git rev-parse HEAD).Trim()
    if ($initialLocal -ne $initialRemote) {
        throw "Local Git baseline mismatch: local=$initialLocal origin/$Branch=$initialRemote. Synchronize and review before publishing."
    }

    $sourceVenvPython = Join-Path $SourceRoot ".venv\Scripts\python.exe"
    $scanPython = if (Test-Path -LiteralPath $sourceVenvPython -PathType Leaf) {
        $sourceVenvPython
    }
    else {
        (Get-Command python -ErrorAction Stop).Source
    }
    Invoke-Checked $scanPython @(
        "scripts/check_public_metadata.py",
        "docs/migration/phase-b0-manifest.json",
        "docs/migration/phase-b0-report.md"
    )

    if ($Verify) {
        if (-not $IsWindows) {
            throw "Full -Verify requires Windows because the WPS release gate includes DPAPI and packaged EXE verification."
        }
        $nodeTestFiles = $testFiles | Where-Object { $_ -like "*.test.mjs" }

        Invoke-Checked $scanPython @("-m", "pytest")
        Invoke-Checked $scanPython @("-m", "ruff", "check", "src", "tests", "scripts")
        if ($nodeTestFiles) {
            Invoke-Checked node (@("--test") + $nodeTestFiles)
        }
        Invoke-Checked pwsh @("-NoProfile", "-File", "apps/wps/scripts/verify.ps1")
        Invoke-Checked pwsh @(
            "-NoProfile", "-File", "apps/wps/scripts/build-exe.ps1",
            "-ServerOrigin", "https://acceptance.invalid"
        )
    }

    if ($DryRun) {
        $statusArguments = @("status", "--short", "--") + $publishFiles
        $publishStatus = & git @statusArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to inspect allowlisted publish changes."
        }
        if ($publishStatus) {
            Write-Host "Allowlisted publish changes:"
            $publishStatus | ForEach-Object { Write-Host $_ }
        }
        else {
            Write-Host "No publish changes detected."
        }
        Write-Host "Dry run complete. No commit was created and nothing was pushed."
        return
    }

    $addArguments = @("add", "--") + $publishFiles
    Invoke-Checked git $addArguments
    $stagedByScript = $true
    Invoke-Checked git @("diff", "--cached", "--check")

    $staged = @(git diff --cached --name-status)
    if (-not $staged) {
        Write-Host "No publish changes detected."
        return
    }

    Write-Host "Staged local publish changes:"
    $staged | ForEach-Object { Write-Host $_ }

    Invoke-Checked git @("commit", "-m", $CommitMessage)
    $commitCreated = $true
    $localCommit = (git rev-parse HEAD).Trim()
    Invoke-Checked git @("push", "origin", "HEAD:$Branch")
    if ($Verify) {
        $remoteLine = (git ls-remote $Repository "refs/heads/$Branch").Trim()
        $remoteCommit = ($remoteLine -split "\s+")[0]
        if ($remoteCommit -ne $localCommit) {
            throw "Push verification failed: local=$localCommit remote=$remoteCommit"
        }
        Write-Host "Full remote commit verification passed: $remoteCommit"
    }
    $publishResult = if ($Verify) { "pushed and fully verified" } else { "pushed" }
    Write-Host "Local commit ${publishResult}: $Repository $Branch $localCommit"
}
finally {
    if ($stagedByScript -and -not $commitCreated) {
        & git restore --staged -- $publishFiles
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Unable to clear the publish staging area after failure. Inspect the index before retrying."
        }
    }
    Pop-Location
}
