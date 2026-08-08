param()

$ErrorActionPreference = "Stop"
$appRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$repoRoot = (Resolve-Path (Join-Path $appRoot "..\..")).Path
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }

Push-Location $repoRoot
try {
    & $python "apps/wps/main.py" verify
    if ($LASTEXITCODE) { throw "WPS_APP_VERIFY_FAILED" }

    & $python -m pytest "apps/wps/tests" -q
    if ($LASTEXITCODE) { throw "WPS_APP_TESTS_FAILED" }

    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        throw "NODE_NOT_FOUND"
    }
    & node --check "apps/wps/main.js"
    if ($LASTEXITCODE) { throw "WPS_MAIN_JS_CHECK_FAILED" }
    & node --check "apps/wps/taskpane.js"
    if ($LASTEXITCODE) { throw "WPS_TASKPANE_JS_CHECK_FAILED" }

    [xml](Get-Content -LiteralPath "apps/wps/manifest.xml" -Raw) | Out-Null
    [xml](Get-Content -LiteralPath "apps/wps/ribbon.xml" -Raw) | Out-Null
    Get-Content -LiteralPath "apps/wps/package.json" -Raw | ConvertFrom-Json | Out-Null

    Write-Output "WPS_APP_GATE_PASS"
} finally {
    Pop-Location
}
