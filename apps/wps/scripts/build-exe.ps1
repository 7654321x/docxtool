param(
    [Parameter(Mandatory = $true)]
    [string]$ServerOrigin,
    [string]$Python = "",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
if (-not $Python) {
    $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python executable not found: $Python"
}

$origin = $null
if (-not [Uri]::TryCreate($ServerOrigin, [UriKind]::Absolute, [ref]$origin) -or
    $origin.Scheme -ne "https" -or
    -not $origin.Host -or
    $origin.UserInfo -or
    $origin.AbsolutePath -ne "/" -or
    $origin.Query -or
    $origin.Fragment) {
    throw "ServerOrigin must be an HTTPS origin without a path, query, or fragment."
}

if (-not $SkipInstall) {
    & $Python -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot "apps\wps\requirements-build.txt")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed." }
}

$env:DOCXTOOL_WPS_SERVER_ORIGIN = $ServerOrigin.TrimEnd("/")
$spec = Join-Path $ProjectRoot "apps\wps\DocxToolWps.spec"
$dist = Join-Path $ProjectRoot "dist\wps"
$work = Join-Path $ProjectRoot "build\wps"
& $Python -m PyInstaller --noconfirm --clean --distpath $dist --workpath $work $spec
if ($LASTEXITCODE -ne 0) { throw "WPS EXE build failed." }

$exe = Join-Path $dist "DocxToolWps.exe"
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "WPS EXE output is missing: $exe"
}

$outsideRoot = Join-Path $env:TEMP ("docxtool-wps-verify-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $outsideRoot | Out-Null
try {
    Push-Location -LiteralPath $outsideRoot
    try {
        $verifyProcess = Start-Process -FilePath $exe -ArgumentList "verify" -WorkingDirectory $outsideRoot -Wait -PassThru
        if ($verifyProcess.ExitCode -ne 0) { throw "Packaged WPS verify command failed with exit code $($verifyProcess.ExitCode)." }
    }
    finally {
        Pop-Location
    }
}
finally {
    Remove-Item -LiteralPath $outsideRoot -Recurse -Force
}

Write-Host "WPS_EXE_BUILD_PASS"
Write-Host "Output: $exe"
