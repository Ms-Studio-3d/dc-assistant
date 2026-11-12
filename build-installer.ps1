param([string]$Python = "python", [switch]$SkipAppBuild)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location -LiteralPath $projectRoot
try {
    if (-not $SkipAppBuild) {
        & ./build-windows.ps1 -Python $Python
        if (-not $?) { throw "Application build failed" }
    }
    $toolsPath = Join-Path $projectRoot "build-tools"
    & $Python tools/prepare_nsis.py $toolsPath
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare the installer compiler" }
    & $Python tools/prepare_installer.py
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare installer payload" }
    $compiler = Join-Path $toolsPath "nsis-3.13\makensis.exe"
    & $compiler /V2 /WX installer/setup.nsi
    if ($LASTEXITCODE -ne 0) { throw "Setup build failed" }
} finally {
    Pop-Location
}
