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
    $javaScriptFiles = @(
        "apps/wps/main.js",
        "apps/wps/js/bootstrap-log.js",
        "apps/wps/js/bootstrap-complete.js",
        "apps/wps/js/ribbon.js",
        "apps/wps/host-runtime.js",
        "apps/wps/taskpane.js",
        "apps/wps/format-config.js",
        "apps/wps/format-settings.js"
    )
    foreach ($javaScriptFile in $javaScriptFiles) {
        & node --check $javaScriptFile
        if ($LASTEXITCODE) { throw "WPS_JAVASCRIPT_CHECK_FAILED: $javaScriptFile" }
    }

    & node --test "apps/wps/tests/run-node-tests.mjs"
    if ($LASTEXITCODE) { throw "WPS_JAVASCRIPT_RUNTIME_TESTS_FAILED" }

    if (-not (Test-Path -LiteralPath "apps/wps/index.html" -PathType Leaf)) {
        throw "WPS_ROOT_INDEX_MISSING"
    }
    Get-Content -LiteralPath "apps/wps/index.html" -Raw | Out-Null

    [xml](Get-Content -LiteralPath "apps/wps/manifest.xml" -Raw) | Out-Null
    [xml](Get-Content -LiteralPath "apps/wps/ribbon.xml" -Raw) | Out-Null
    Get-Content -LiteralPath "apps/wps/package.json" -Raw | ConvertFrom-Json | Out-Null
    Get-Content -LiteralPath "apps/wps/package-lock.json" -Raw | ConvertFrom-Json -AsHashtable | Out-Null

    Write-Output "WPS_APP_GATE_PASS"
} finally {
    Pop-Location
}
