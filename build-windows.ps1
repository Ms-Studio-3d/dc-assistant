param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location -LiteralPath $projectRoot
try {
    & $Python -m black --check --workers 1 dc_assistant tests launcher.py
    if ($LASTEXITCODE -ne 0) { throw "Code formatting check failed" }
    & $Python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
    $buildArguments = @(
        '-m', 'PyInstaller',
        '--noconfirm', '--onedir', '--windowed', '--noupx',
        '--collect-data', 'pdfminer',
        '--collect-binaries', 'pypdfium2_raw',
        '--exclude-module', 'numpy',
        '--exclude-module', 'pandas',
        '--exclude-module', 'scipy',
        '--exclude-module', 'matplotlib',
        '--exclude-module', 'lxml',
        '--name', 'DC-Assistant',
        '--distpath', 'dist',
        '--workpath', 'build',
        'launcher.py'
    )
    & $Python @buildArguments
    if ($LASTEXITCODE -ne 0) { throw "EXE build failed" }
    $application = Join-Path $projectRoot "dist\DC-Assistant\DC-Assistant.exe"
    $reportPath = Join-Path $projectRoot "build\self-test-report.json"
    $testData = Join-Path $projectRoot "build\self-test-data"
    $testArguments = @(
        '--self-test-report', ('"' + $reportPath + '"'),
        '--data-dir', ('"' + $testData + '"')
    )
    $testProcess = Start-Process -FilePath $application -ArgumentList $testArguments -WindowStyle Hidden -Wait -PassThru
    if ($testProcess.ExitCode -ne 0) { throw "Packaged application self-test failed" }
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if (-not $report.passed) { throw "Packaged application self-test failed" }
    Write-Output $application
} finally {
    Pop-Location
}
