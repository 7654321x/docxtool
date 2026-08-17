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

function New-WpsApplicationIcon {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    Add-Type -AssemblyName System.Drawing
    $sourceImage = [System.Drawing.Image]::FromFile($Source)
    $canvas = [System.Drawing.Bitmap]::new(256, 256, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($canvas)
    $icon = $null
    $stream = $null
    try {
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $ratio = [Math]::Min(256 / $sourceImage.Width, 256 / $sourceImage.Height)
        $width = [int][Math]::Round($sourceImage.Width * $ratio)
        $height = [int][Math]::Round($sourceImage.Height * $ratio)
        $x = [int][Math]::Floor((256 - $width) / 2)
        $y = [int][Math]::Floor((256 - $height) / 2)
        $graphics.DrawImage($sourceImage, [System.Drawing.Rectangle]::new($x, $y, $width, $height))

        $directory = Split-Path -Parent $Destination
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
        $icon = [System.Drawing.Icon]::FromHandle($canvas.GetHicon())
        $stream = [System.IO.File]::Open(
            $Destination,
            [System.IO.FileMode]::Create,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        $icon.Save($stream)
    }
    finally {
        if ($stream) { $stream.Dispose() }
        if ($icon) { $icon.Dispose() }
        $graphics.Dispose()
        $canvas.Dispose()
        $sourceImage.Dispose()
    }

    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) {
        throw "WPS application icon output is missing: $Destination"
    }
}

function Assert-WindowedExecutable {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
    $reader = [System.IO.BinaryReader]::new($stream)
    try {
        $stream.Position = 0x3C
        $peOffset = $reader.ReadInt32()
        $stream.Position = $peOffset
        if ($reader.ReadUInt32() -ne 0x00004550) {
            throw "WPS EXE does not contain a valid PE header."
        }
        $optionalHeaderOffset = $peOffset + 4 + 20
        $stream.Position = $optionalHeaderOffset + 68
        $subsystem = $reader.ReadUInt16()
        if ($subsystem -ne 2) {
            throw "WPS EXE is not a windowed application (PE subsystem: $subsystem)."
        }
    }
    finally {
        $reader.Dispose()
    }
}

if (-not $SkipInstall) {
    & $Python -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot "apps\wps\requirements-build.txt")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed." }
}

$env:DOCXTOOL_WPS_SERVER_ORIGIN = $ServerOrigin.TrimEnd("/")
$spec = Join-Path $ProjectRoot "apps\wps\DocxToolWps.spec"
$dist = Join-Path $ProjectRoot "dist\wps"
$work = Join-Path $ProjectRoot "build\wps"
$iconSource = Join-Path $ProjectRoot "apps\wps\images\login-window.png"
$icon = Join-Path $ProjectRoot "build\wps-client\docxtool-wps.ico"
New-WpsApplicationIcon -Source $iconSource -Destination $icon
& $Python -m PyInstaller --noconfirm --clean --distpath $dist --workpath $work $spec
if ($LASTEXITCODE -ne 0) { throw "WPS EXE build failed." }

$exe = Join-Path $dist "DocxToolWps.exe"
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "WPS EXE output is missing: $exe"
}
Assert-WindowedExecutable -Path $exe

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
Write-Host "WPS_EXE_WINDOWED_PASS"
Write-Host "Output: $exe"
