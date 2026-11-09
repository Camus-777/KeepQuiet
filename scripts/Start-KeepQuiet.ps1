param([switch]$Benchmark, [int]$InputId = -1, [int]$OutputId = -1)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = (Get-Command python.exe).Source }
if ($Benchmark) {
    if ($InputId -ge 0 -and $OutputId -ge 0) {
        & $taskPython -X utf8 -m keepquiet benchmark --input $InputId --output $OutputId
    } else {
        & $taskPython -X utf8 -m keepquiet benchmark
    }
} else {
    # Priority is applied and reverted inside the isolated audio worker. The UI
    # remains at Normal and Windows is never switched to REALTIME_PRIORITY_CLASS.
    Start-Process -FilePath $taskPython -ArgumentList '-m','keepquiet','ui' -WorkingDirectory $taskRoot
}
