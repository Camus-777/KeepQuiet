$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 is required to build from source.' }
}
& '.venv\Scripts\python.exe' -m pip install -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.venv\Scripts\python.exe' -m keepquiet prepare
if ($LASTEXITCODE -ne 0) { throw 'Model verification failed.' }
Write-Host 'KeepQuiet ready. Run .\scripts\Start-KeepQuiet.ps1'
