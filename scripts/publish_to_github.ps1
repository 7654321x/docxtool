#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Quick,
    [switch]$Verify,
    [switch]$IncludeDeploymentPackage,
    [string]$Repository = "git@github.com:7654321x/docxtool.git",
    [string]$Branch = "main",
    [string]$SourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path,
    [string]$CommitMessage = "Sync project files"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($Quick -and $Verify) {
    throw "-Quick and -Verify cannot be used together. Choose one publish verification level."
}
if (-not $CommitMessage.Trim()) {
    throw "CommitMessage cannot be empty."
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

function Assert-CleanIndex {
    $staged = @(git diff --cached --name-status)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the local Git index."
    }
    if ($staged) {
        throw "The local Git index already contains staged changes. Commit or unstage them before publishing."
    }
}

function Get-ChangedFiles {
    $tracked = @(git -c core.quotePath=false diff --name-only --relative)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect tracked working-tree changes."
    }
    $untracked = @(git -c core.quotePath=false ls-files --others --exclude-standard)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect untracked working-tree files."
    }
    return @($tracked + $untracked | ForEach-Object {
        $_.Trim().Replace("\", "/")
    } | Where-Object { $_ } | Sort-Object -Unique)
}

function Assert-PublishScope {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$RelativePaths
    )

    $deploymentChanges = @($RelativePaths | Where-Object { $_ -match '^docxtool/' })
    if ($deploymentChanges -and -not $IncludeDeploymentPackage) {
        throw "Deployment package changes require -IncludeDeploymentPackage:`n$($deploymentChanges -join "`n")"
    }

    $forbidden = @($RelativePaths | Where-Object {
        $relative = $_.Replace("\", "/")
        if ($relative -in @('.env.example', 'docxtool/.env.example')) {
            return $false
        }
        $relative -match '(^|/)\.env(\.|$)' -or
        $relative -match '\.(pem|key|db|sqlite|sqlite3|log|zip|exe|whl|docx)$' -or
        $relative -match '(^|/)(__pycache__|logs|outputs|runtime|build|dist|tmp_wheels|node_modules|local_recycle|test_docx|\.venv|\.pytest_cache|\.ruff_cache|\.playwright-mcp)(/|$)' -or
        $relative -in @('apps/wps/runtime/runtime-config.js', 'apps/wps/publish.xml', 'apps/wps/authaddin.json')
    })
    if ($forbidden) {
        throw "Forbidden files found in pending Git changes:`n$($forbidden -join "`n")"
    }
}

function Invoke-PathspecGitAdd {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$RelativePaths
    )

    $pathspecFile = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllLines(
            $pathspecFile,
            $RelativePaths,
            [System.Text.UTF8Encoding]::new($false)
        )
        Invoke-Checked git @("add", "-A", "--pathspec-from-file=$pathspecFile")
    }
    finally {
        Remove-Item -LiteralPath $pathspecFile -Force -ErrorAction SilentlyContinue
    }
}

function Clear-PublishIndex {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$RelativePaths
    )

    if (-not $RelativePaths) {
        return
    }
    $pathspecFile = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllLines(
            $pathspecFile,
            $RelativePaths,
            [System.Text.UTF8Encoding]::new($false)
        )
        & git restore --staged "--pathspec-from-file=$pathspecFile"
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Unable to clear the publish staging area after failure. Inspect the index before retrying."
        }
    }
    finally {
        Remove-Item -LiteralPath $pathspecFile -Force -ErrorAction SilentlyContinue
    }
}

$stagedByScript = $false
$commitCreated = $false
$publishFiles = @()
$verificationMode = if ($Verify) { "full" } else { "quick" }

Write-Host "Source: $SourceRoot"
Write-Host "Repository: $Repository"
Write-Host "Branch: $Branch"
Write-Host "Deployment package: $(if ($IncludeDeploymentPackage) { 'included' } else { 'excluded' })"
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
    if ($LASTEXITCODE -ne 0 -or $pushUrl -ne $Repository -or $pushUrl -notmatch '^git@github\.com:') {
        throw "The origin push URL must match the configured GitHub SSH repository: expected=$Repository actual=$pushUrl"
    }
    if ($Repository -notmatch '^git@github\.com:') {
        throw "Repository must use a GitHub SSH URL: $Repository"
    }

    Assert-CleanIndex
    $publishFiles = @(Get-ChangedFiles)
    Assert-PublishScope -RelativePaths $publishFiles

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
        $nodeTestFiles = @(Get-ChildItem -LiteralPath "tests", "apps/wps/tests" -File -Recurse -Filter "*.test.mjs" |
            ForEach-Object { [System.IO.Path]::GetRelativePath($SourceRoot, $_.FullName) })
        Invoke-Checked $scanPython @("-m", "pytest")
        Invoke-Checked $scanPython @("-m", "ruff", "check", "src", "tests", "scripts")
        if ($nodeTestFiles) {
            Invoke-Checked node (@("--test") + $nodeTestFiles)
        }
        Invoke-Checked pwsh @("-NoProfile", "-File", "apps/wps/scripts/verify.ps1")
        Invoke-Checked pwsh @(
            "-NoProfile", "-File", "apps/wps/scripts/build-exe.ps1",
            "-PublicApiBaseUrl", "https://acceptance.invalid"
        )
    }
    elseif (-not $DryRun) {
        Invoke-Checked pwsh @(
            "-NoProfile", "-File", "scripts/verify_changed.ps1", "-SkipPublishDryRun"
        )
    }

    if ($DryRun) {
        if ($publishFiles) {
            Write-Host "Pending publish changes:"
            git status --short --untracked-files=all
            if ($LASTEXITCODE -ne 0) {
                throw "Unable to inspect local publish changes."
            }
        }
        else {
            Write-Host "No publish changes detected."
        }
        Write-Host "Dry run complete. No commit was created and nothing was pushed."
        return
    }

    if (-not $publishFiles) {
        Write-Host "No publish changes detected."
        return
    }

    $stagedByScript = $true
    Invoke-PathspecGitAdd -RelativePaths $publishFiles
    if ($IncludeDeploymentPackage) {
        Invoke-Checked git @("update-index", "--chmod=+x", "--", "docxtool/setup.sh", "docxtool/start.sh")
    }
    Invoke-Checked git @("diff", "--cached", "--check")

    $remaining = @(Get-ChangedFiles)
    if ($remaining) {
        throw "Publish staging omitted working-tree changes:`n$($remaining -join "`n")"
    }

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

    $remoteLine = (git ls-remote $Repository "refs/heads/$Branch").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $remoteLine) {
        throw "Unable to verify the pushed remote commit."
    }
    $remoteCommit = ($remoteLine -split "\s+")[0]
    if ($remoteCommit -ne $localCommit) {
        throw "Push verification failed: local=$localCommit remote=$remoteCommit"
    }

    $workingTreeClean = -not @(git status --porcelain --untracked-files=all)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the final working tree."
    }
    if (-not $workingTreeClean) {
        throw "Push completed, but the working tree is not clean."
    }

    Write-Host "PUBLISH_PASS"
    Write-Host "Commit SHA: $localCommit"
    Write-Host "Commit message: $CommitMessage"
    Write-Host "Branch: $Branch"
    Write-Host "Verification: $verificationMode"
    Write-Host "Working tree clean: true"
}
finally {
    if ($stagedByScript -and -not $commitCreated) {
        Clear-PublishIndex -RelativePaths $publishFiles
    }
    Pop-Location
}
