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
$requirements = Join-Path $root "requirements.txt"
$envFile = Join-Path $root ".env"
$taskName = "DocxtoolBackend"
$srcDirectory = Join-Path $root "src"
$pythonRuntime = $null

function Assert-BackendPrerequisites {
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        throw "Missing .env next to run.ps1. Create it from .env.example and configure production values."
    }
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Installing the Windows scheduled task requires an administrator PowerShell 7 session."
    }
}

function Install-BackendDependencies {
    if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
        throw "Missing requirements.txt next to run.ps1."
    }
    Invoke-BackendPython @("-m", "pip", "install", "-r", $requirements)
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to verify or install project dependencies."
    }
}

function Resolve-BackendPython {
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue

    if ($pyLauncher) {
        foreach ($selector in @("-3.11", "-3.10", "-3")) {
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
        return [pscustomobject]@{
            Executable = $python.Source
            Prefix = @()
            Display = $python.Source
        }
    }

    throw "Python was not found. Install Python 3.11 or Python 3.10 and ensure py.exe or python.exe is available."
}

function Invoke-BackendPython {
    param([string[]]$Arguments)
    $allArguments = @($pythonRuntime.Prefix) + @($Arguments)
    & $pythonRuntime.Executable @allArguments
}

function Get-CurrentPowerShellExecutable {
    $hostProcess = Get-Process -Id $PID -ErrorAction Stop
    if (-not $hostProcess.Path) {
        throw "Unable to locate the current PowerShell executable."
    }
    return $hostProcess.Path
}

function Register-BackendTask {
    Assert-Administrator
    Assert-BackendPrerequisites
    $powershell = Get-CurrentPowerShellExecutable
    $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ServiceRun"
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $root
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
    Write-Host "Installed and started Windows scheduled task: $taskName"
    Write-Host "Backend health check: http://127.0.0.1:9527/health"
}

Push-Location -LiteralPath $root
try {
    if ($UninstallService) {
        Assert-Administrator
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Write-Host "Uninstalled Windows scheduled task: $taskName"
        }
        else {
            Write-Host "Scheduled task is not installed: $taskName"
        }
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
