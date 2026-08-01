#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Verify,
    [string]$Repository = "https://github.com/7654321x/docxtool.git",
    [string]$Branch = "main",
    [string]$SourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path,
    [string]$CommitMessage = "Sync project files",
    [switch]$KeepTemp
)

$ErrorActionPreference = "Stop"

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

function Copy-RequiredFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath,
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $from = Join-Path $Source $RelativePath
    if (-not (Test-Path -LiteralPath $from -PathType Leaf)) {
        throw "Required publish file is missing: $RelativePath"
    }

    $to = Join-Path $Destination $RelativePath
    $parent = Split-Path -Parent $to
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Copy-Item -LiteralPath $from -Destination $to -Force
}

function Clear-CloneWorktree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CloneRoot
    )

    $resolved = (Resolve-Path -LiteralPath $CloneRoot).Path
    if (-not $resolved.StartsWith($env:TEMP, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clear a clone outside TEMP: $resolved"
    }

    Get-ChildItem -LiteralPath $resolved -Force |
        Where-Object { $_.Name -ne ".git" } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
}

function Assert-NoForbiddenFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CloneRoot
    )

    $forbidden = Get-ChildItem -LiteralPath $CloneRoot -Force -Recurse -File |
        Where-Object {
            $relative = [System.IO.Path]::GetRelativePath($CloneRoot, $_.FullName).Replace("\", "/")
            if ($relative -match '^var/(data|logs|outputs|runtime)/\.gitkeep$') {
                return $false
            }
            if ($relative -match '^\.git/') {
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
        $list = ($forbidden | ForEach-Object { [System.IO.Path]::GetRelativePath($CloneRoot, $_.FullName) }) -join "`n"
        throw "Forbidden files found in publish clone:`n$list"
    }
}

$requiredFiles = @(
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "CHANGELOG.md",
    "docs/API.md",
    "docs/SDK.md",
    "docs/ARCHITECTURE_DAG.md",
    "docs/INTEGRATION_CONTRACT_V1.md",
    "docs/HOST_ADAPTER_GUIDE.md",
    "docs/examples/sdk-contract-examples.md",
    "docs/RECOGNITION_SOURCE_LOCATORS.md",
    "docs/HOST_TEXT_V1_GOLDEN.json",
    "docs/USER_WPS_VALIDATION.md",
    "docs/USER_WPS_VALIDATION_RESULT.md",
    "公文格式规范.md",
    "CONVENTIONS.md",
    "docs/DEPLOY.md",
    "docs/RECOGNITION_ARCHITECTURE.md",
    "docs/RECOGNITION_RELEASE.md",
    "docs/DOCX_REGRESSION_CHECKLIST.md",
    "docs/GITHUB_UPLOAD_GUIDE.md",
    "README.md",
    "docs/UPLOAD_MANIFEST.md",
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
    "src/docxtool/web/admin_auth.py",
    "src/docxtool/web/anonymous_identity.py",
    "src/docxtool/web/client_ip.py",
    "src/docxtool/web/config.py",
    "src/docxtool/web/database_schema.py",
    "src/docxtool/web/file_utils.py",
    "src/docxtool/web/format_request.py",
    "src/docxtool/web/health.py",
    "src/docxtool/web/monitoring.py",
    "src/docxtool/web/owner_migration.py",
    "src/docxtool/web/preset_config.py",
    "src/docxtool/web/preset_defaults.py",
    "src/docxtool/web/preset_store.py",
    "src/docxtool/web/rate_limits.py",
    "src/docxtool/web/request_utils.py",
    "src/docxtool/web/secrets.py",
    "src/docxtool/web/stream_io.py",
    "src/docxtool/web/task_cache.py",
    "src/docxtool/web/task_paths.py",
    "src/docxtool/web/task_records.py",
    "src/docxtool/web/task_recovery.py",
    "src/docxtool/web/task_result.py",
    "src/docxtool/web/task_statistics.py",
    "src/docxtool/web/task_state.py",
    "src/docxtool/web/time_check.py",
    "src/docxtool/web/user_auth.py",
    "src/docxtool/document/__init__.py",
    "src/docxtool/document/classifier.py",
    "src/docxtool/document/importer.py",
    "src/docxtool/document/effective_format.py",
    "src/docxtool/document/source_tape.py",
    "src/docxtool/document/models/__init__.py",
    "src/docxtool/document/models/document.py",
    "src/docxtool/document/models/paragraph.py",
    "src/docxtool/document/models/source.py",
    "src/docxtool/document/normalization/__init__.py",
    "src/docxtool/document/normalization/tail.py",
    "src/docxtool/document/segmentation/__init__.py",
    "src/docxtool/document/segmentation/boundaries.py",
    "src/docxtool/document/segmentation/source_locator.py",
    "src/docxtool/document/letterhead_config.py",
    "src/docxtool/document/recognition/__init__.py",
    "src/docxtool/document/recognition/candidates.py",
    "src/docxtool/document/recognition/colon.py",
    "src/docxtool/document/recognition/compatibility.py",
    "src/docxtool/document/recognition/config.py",
    "src/docxtool/document/recognition/decoder.py",
    "src/docxtool/document/recognition/diagnostics.py",
    "src/docxtool/document/recognition/features.py",
    "src/docxtool/document/recognition/global_context.py",
    "src/docxtool/document/recognition/model.py",
    "src/docxtool/document/recognition/validators.py",
    "src/docxtool/document/recognition/version.py",
    "src/docxtool/document/style_config.py",
    "src/docxtool/document/engine/__init__.py",
    "src/docxtool/document/engine/cleanup.py",
    "src/docxtool/document/engine/context_candidate.py",
    "src/docxtool/document/engine/core.py",
    "src/docxtool/document/engine/document_structure.py",
    "src/docxtool/document/engine/letterhead.py",
    "src/docxtool/document/engine/normal.py",
    "src/docxtool/document/engine/numbering.py",
    "src/docxtool/document/engine/page_number.py",
    "src/docxtool/document/engine/punctuation.py",
    "src/docxtool/document/engine/punctuation_docx.py",
    "src/docxtool/document/engine/signature_block.py",
    "src/docxtool/document/engine/structure_context.py",
    "src/docxtool/document/engine/style_catalog.py",
    "src/docxtool/document/engine/table.py",
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
    "scripts/generate_005_format_fixtures.py",
    "scripts/generate_wps_validation_fixtures.py",
    "scripts/normalize_correct_template_role_spacing.py",
    "scripts/migrate_legacy_database.ps1",
    "scripts/publish_to_github.ps1",
    "resources/frontend/pages/index.html",
    "resources/frontend/pages/_worker.js",
    "var/data/.gitkeep",
    "var/logs/.gitkeep",
    "var/outputs/.gitkeep",
    "var/runtime/.gitkeep"
)

$testFiles = Get-ChildItem -LiteralPath (Join-Path $SourceRoot "tests") -File |
    Where-Object { $_.Name -like "test_*.py" -or $_.Name -like "*.test.mjs" } |
    ForEach-Object { "tests/$($_.Name)" }
$publishFiles = @($requiredFiles + $testFiles | Sort-Object -Unique)
$tempRoot = Join-Path $env:TEMP ("docxtool-publish-" + [guid]::NewGuid().ToString("N"))

try {
    Write-Host "Source: $SourceRoot"
    Write-Host "Repository: $Repository"
    Write-Host "Branch: $Branch"
    Write-Host "Mode: $(if ($DryRun) { 'dry-run' } else { 'push' })"

    Invoke-Checked git @("clone", "--branch", $Branch, "--single-branch", $Repository, $tempRoot)
    Push-Location -LiteralPath $tempRoot
    try {
        $initialRemote = (git rev-parse "origin/$Branch").Trim()

        Clear-CloneWorktree -CloneRoot $tempRoot
        foreach ($file in $publishFiles) {
            Copy-RequiredFile -RelativePath $file -Source $SourceRoot -Destination $tempRoot
        }

        Assert-NoForbiddenFiles -CloneRoot $tempRoot

        if ($Verify) {
            $sourceVenvPython = Join-Path $SourceRoot ".venv\Scripts\python.exe"
            $testPython = if (Test-Path -LiteralPath $sourceVenvPython -PathType Leaf) {
                $sourceVenvPython
            }
            else {
                (Get-Command python -ErrorAction Stop).Source
            }
            $nodeTestFiles = $testFiles | Where-Object { $_ -like "*.test.mjs" }

            Invoke-Checked $testPython @("-m", "pytest")
            Invoke-Checked $testPython @("-m", "ruff", "check", "src", "tests", "scripts")
            if ($nodeTestFiles) {
                Invoke-Checked node (@("--test") + $nodeTestFiles)
            }
        }

        Invoke-Checked git @("add", "-A")
        Invoke-Checked git @("diff", "--cached", "--check")

        $staged = git diff --cached --name-status
        if (-not $staged) {
            Write-Host "No publish changes detected."
            return
        }

        Write-Host "Staged publish changes:"
        $staged | ForEach-Object { Write-Host $_ }

        Invoke-Checked git @("fetch", "origin", $Branch)
        $latestRemote = (git rev-parse "origin/$Branch").Trim()
        if ($latestRemote -ne $initialRemote) {
            throw "Remote $Branch changed after clone ($initialRemote -> $latestRemote). Stop and review before pushing."
        }

        if ($DryRun) {
            Write-Host "Dry run complete. No commit was created and nothing was pushed."
            return
        }

        Invoke-Checked git @("config", "user.name", "7654321x")
        Invoke-Checked git @("config", "user.email", "7654321x@users.noreply.github.com")
        Invoke-Checked git @("commit", "-m", $CommitMessage)
        $localCommit = (git rev-parse HEAD).Trim()
        Invoke-Checked git @("push", "origin", "HEAD:$Branch")
        $remoteLine = (git ls-remote $Repository "refs/heads/$Branch").Trim()
        $remoteCommit = ($remoteLine -split "\s+")[0]
        if ($remoteCommit -ne $localCommit) {
            throw "Push verification failed: local=$localCommit remote=$remoteCommit"
        }
        Write-Host "Pushed and verified: $Repository $Branch $localCommit"
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($KeepTemp) {
        Write-Host "Keeping temp clone: $tempRoot"
    }
    elseif (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
