param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location -LiteralPath $projectRoot
try {
    & $Python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
    & $Python -m PyInstaller --noconfirm --onedir --windowed --noupx --exclude-module numpy --exclude-module pandas --exclude-module scipy --exclude-module matplotlib --exclude-module lxml --name "DC-Assistant" --distpath dist --workpath build launcher.py
    if ($LASTEXITCODE -ne 0) { throw "EXE build failed" }
    $application = Join-Path $projectRoot "dist\DC-Assistant\DC-Assistant.exe"
    $reportPath = Join-Path $projectRoot "build\self-test-report.json"
    $testData = Join-Path $projectRoot "build\self-test-data"
    $testProcess = Start-Process -FilePath $application -ArgumentList @('--self-test-report',('"' + $reportPath + '"'),'--data-dir',('"' + $testData + '"')) -WindowStyle Hidden -Wait -PassThru
    if ($testProcess.ExitCode -ne 0) { throw "Packaged application self-test failed" }
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if (-not $report.passed) { throw "Packaged application self-test failed" }
    Write-Output $application
} finally {
    Pop-Location
}
