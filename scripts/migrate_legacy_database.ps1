#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$Execute,
    [string]$Source = "stats.db",
    [string]$Destination = "var/data/stats.db"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$sourcePath = Join-Path $root $Source
$destinationPath = Join-Path $root $Destination

function Test-SqliteIntegrity {
    param([Parameter(Mandatory = $true)][string]$Path)

    $code = "import sqlite3, sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('pragma integrity_check').fetchone()[0]); c.close()"
    $result = & python -c $code $Path
    if ($LASTEXITCODE -ne 0) {
        throw "sqlite integrity_check command failed for $Path"
    }
    if ($result -ne "ok") {
        throw "sqlite integrity_check failed for $Path`: $result"
    }
    return $result
}

Write-Host "Legacy database migration plan"
Write-Host "Source:      $sourcePath"
Write-Host "Destination: $destinationPath"
Write-Host "This script copies the database. It never deletes the legacy database."
Write-Host "Stop the Docxtool service before running with -Execute."

if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
    throw "Legacy database not found: $sourcePath"
}

if (Test-Path -LiteralPath $destinationPath) {
    throw "Destination already exists; refusing to overwrite: $destinationPath"
}

Write-Host "Checking source integrity..."
Test-SqliteIntegrity -Path $sourcePath | Out-Null
Write-Host "Source integrity: ok"

if (-not $Execute) {
    Write-Host "Dry run complete. Re-run with -Execute to copy the database."
    return
}

$backupPath = "$sourcePath.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -LiteralPath $sourcePath -Destination $backupPath -Force
Write-Host "Backup created: $backupPath"

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinationPath) | Out-Null
Copy-Item -LiteralPath $sourcePath -Destination $destinationPath

Write-Host "Checking destination integrity..."
Test-SqliteIntegrity -Path $destinationPath | Out-Null
Write-Host "Destination integrity: ok"
Write-Host "Migration copy complete. Set DATABASE_PATH=var/data/stats.db after verifying the service is stopped and configuration is ready."
