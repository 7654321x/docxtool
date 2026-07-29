#requires -Version 5.1

[CmdletBinding()]
param(
    [switch]$InstallDependencies,
    [switch]$CheckOnly,
    [switch]$InstallService,
    [switch]$UninstallService,
    [switch]$ServiceRun
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$requirementsLock = Join-Path $root "requirements.lock"
$envFile = Join-Path $root ".env"
$taskName = "DocxtoolBackend"
$srcDirectory = Join-Path $root "src"
$pythonRuntime = $null
$supportedPythonMessage = "Python 3.8, 3.9, or 3.10"

function Test-SupportedPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$Prefix = @()
    )

    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Executable @Prefix -c "import sys; raise SystemExit(0 if (3, 8) <= sys.version_info[:2] < (3, 11) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
}

function Get-PythonVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$Prefix = @()
    )

    $version = & $Executable @Prefix -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null
    return (@($version) | Select-Object -Last 1).ToString().Trim()
}

function Assert-BackendPrerequisites {
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        throw "Missing .env next to run.ps1. Create it from .env.example and configure production values."
    }
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Installing the Windows scheduled task requires an administrator PowerShell session."
    }
}

function Install-BackendDependencies {
    if (-not (Test-Path -LiteralPath $requirementsLock -PathType Leaf)) {
        throw "Missing requirements.lock next to run.ps1."
    }
    Invoke-BackendPython @("-m", "pip", "install", "--require-hashes", "-r", $requirementsLock)
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to verify or install project dependencies."
    }
}

function Resolve-BackendPython {
    $override = [string]$env:DOCXTOOL_PYTHON_EXE
    if ($override) {
        if (-not (Test-Path -LiteralPath $override -PathType Leaf)) {
            throw "DOCXTOOL_PYTHON_EXE does not exist: $override"
        }
        $resolvedOverride = (Resolve-Path -LiteralPath $override).Path
        if (-not (Test-SupportedPython -Executable $resolvedOverride)) {
            $actualVersion = Get-PythonVersion -Executable $resolvedOverride
            throw "DOCXTOOL_PYTHON_EXE uses Python $actualVersion. Supported versions are $supportedPythonMessage."
        }
        return [pscustomobject]@{
            Executable = $resolvedOverride
            Prefix = @()
            Display = $resolvedOverride
        }
    }

    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        if (-not (Test-SupportedPython -Executable $venvPython)) {
            $actualVersion = Get-PythonVersion -Executable $venvPython
            throw "The project virtual environment uses Python $actualVersion. Supported versions are $supportedPythonMessage."
        }
        return [pscustomobject]@{
            Executable = $venvPython
            Prefix = @()
            Display = $venvPython
        }
    }

    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue

    if ($pyLauncher) {
        foreach ($selector in @("-3.8", "-3.9", "-3.10")) {
            $previousErrorAction = $ErrorActionPreference
            try {
                # Windows PowerShell 5.1 turns py.exe's missing-version stderr into
                # NativeCommandError when the surrounding script uses Stop.
                $ErrorActionPreference = "Continue"
                & $pyLauncher.Source $selector -c "import sys" *> $null
                $selectorAvailable = $LASTEXITCODE -eq 0
            }
            finally {
                $ErrorActionPreference = $previousErrorAction
            }
            if (-not $selectorAvailable) {
                continue
            }
            return [pscustomobject]@{
                Executable = $pyLauncher.Source
                Prefix = @($selector)
                Display = "$($pyLauncher.Source) $selector"
            }
        }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        if (-not (Test-SupportedPython -Executable $python.Source)) {
            $actualVersion = Get-PythonVersion -Executable $python.Source
            throw "python.exe resolves to Python $actualVersion. Supported versions are $supportedPythonMessage."
        }
        return [pscustomobject]@{
            Executable = $python.Source
            Prefix = @()
            Display = $python.Source
        }
    }

    throw "$supportedPythonMessage was not found. Install a supported runtime and ensure py.exe or python.exe is available."
}

function Invoke-BackendPython {
    param([string[]]$Arguments)
    $allArguments = @($pythonRuntime.Prefix) + @($Arguments)
    & $pythonRuntime.Executable @allArguments
}

function Resolve-ServicePythonExecutable {
    param(
        [Parameter(Mandatory = $true)]
        $Runtime
    )

    # SYSTEM has a different Python launcher registry view from the interactive
    # user. Resolve py.exe once during installation, then schedule the absolute
    # interpreter path so the task does not depend on that per-user state.
    $override = [string]$env:DOCXTOOL_PYTHON_EXE
    if ($override) {
        if (-not (Test-Path -LiteralPath $override -PathType Leaf)) {
            throw "DOCXTOOL_PYTHON_EXE does not exist: $override"
        }
        return (Resolve-Path -LiteralPath $override).Path
    }

    $runtimeName = [IO.Path]::GetFileName([string]$Runtime.Executable)
    if ($runtimeName -ine "py.exe" -and @($Runtime.Prefix).Count -eq 0) {
        return (Resolve-Path -LiteralPath $Runtime.Executable).Path
    }

    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $resolved = & $Runtime.Executable @($Runtime.Prefix) -c "import sys; print(sys.executable)" 2>$null
        $resolvedOk = $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    $servicePython = (@($resolved) | Select-Object -Last 1).ToString().Trim()
    if (-not $resolvedOk -or -not $servicePython -or -not (Test-Path -LiteralPath $servicePython -PathType Leaf)) {
        throw "Unable to resolve an absolute Python executable for the scheduled task. Set DOCXTOOL_PYTHON_EXE if needed."
    }
    return (Resolve-Path -LiteralPath $servicePython).Path
}

function Test-ModernScheduledTaskSupport {
    return (
        $null -ne (Get-Command New-ScheduledTaskAction -ErrorAction SilentlyContinue) -and
        $null -ne (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue) -and
        $null -ne (Get-Command Start-ScheduledTask -ErrorAction SilentlyContinue)
    )
}

function Unregister-BackendTask {
    if (Test-ModernScheduledTaskSupport) {
        $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if (-not $existingTask) {
            Write-Host "Scheduled task is not installed: $taskName"
            return
        }
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Uninstalled Windows scheduled task: $taskName"
        return
    }

    & schtasks.exe /Query /TN $taskName *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Scheduled task is not installed: $taskName"
        return
    }
    & schtasks.exe /End /TN $taskName *> $null
    & schtasks.exe /Delete /TN $taskName /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to remove Windows scheduled task: $taskName"
    }
    Write-Host "Uninstalled Windows scheduled task: $taskName"
}

function Register-BackendTask {
    Assert-Administrator
    Assert-BackendPrerequisites
    $servicePython = Resolve-ServicePythonExecutable -Runtime $pythonRuntime
    $serverPath = Join-Path $root "server.py"

    if (Test-ModernScheduledTaskSupport) {
        $arguments = "-X utf8 `"$serverPath`""
        $action = New-ScheduledTaskAction -Execute $servicePython -Argument $arguments -WorkingDirectory $root
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $settings = New-ScheduledTaskSettingsSet `
            -RestartCount 999 `
            -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -MultipleInstances IgnoreNew `
            -StartWhenAvailable
        $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal `
            -Description "Docxtool Python backend service" `
            -Force | Out-Null
        Start-ScheduledTask -TaskName $taskName
    }
    else {
        $taskCommand = "`"$servicePython`" -X utf8 `"$serverPath`""
        & schtasks.exe /Create /TN $taskName /SC ONSTART /RU SYSTEM /RL HIGHEST /TR $taskCommand /F | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install the Windows 7 scheduled task: $taskName"
        }
        & schtasks.exe /Run /TN $taskName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Installed the task but failed to start it: $taskName"
        }
    }
    Write-Host "Installed and started Windows scheduled task: $taskName"
    Write-Host "Service Python: $servicePython"
    Write-Host "Backend health check: http://127.0.0.1:9527/health"
}

Push-Location -LiteralPath $root
try {
    if ($UninstallService) {
        Assert-Administrator
        Unregister-BackendTask
        return
    }

    $pythonRuntime = Resolve-BackendPython
    Write-Host "Python runtime: $($pythonRuntime.Display)"

    if ($InstallDependencies) {
        Invoke-BackendPython @("-m", "pip", "install", "--upgrade", "pip")
        if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip." }
    }

    # pip skips satisfied requirements and downloads only missing or incompatible packages.
    Install-BackendDependencies

    if ($CheckOnly) {
        $oldPythonPath = $env:PYTHONPATH
        $env:PYTHONPATH = if ($oldPythonPath) { "$srcDirectory;$oldPythonPath" } else { $srcDirectory }
        Invoke-BackendPython @("-c", "import sys, docxtool; print(sys.executable); print(docxtool.__file__)")
        $env:PYTHONPATH = $oldPythonPath
        if ($LASTEXITCODE -ne 0) { throw "Backend entry point check failed." }
        return
    }

    if ($InstallService) {
        Register-BackendTask
        return
    }

    Assert-BackendPrerequisites
    $env:PYTHONUTF8 = "1"
    if ($ServiceRun) {
        $logDirectory = Join-Path $root "var\logs"
        New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
        $consoleLog = Join-Path $logDirectory "service-console.log"
        Invoke-BackendPython @((Join-Path $root "server.py")) *>> $consoleLog
    }
    else {
        Invoke-BackendPython @((Join-Path $root "server.py"))
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Docxtool backend exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
