# Optional per-user deployment for the portable release. No Python required.
$ErrorActionPreference = 'Stop'
$taskSource = Join-Path $PSScriptRoot 'KeepQuiet'
if (-not (Test-Path -LiteralPath (Join-Path $taskSource 'KeepQuiet.exe'))) {
    throw 'Extract the complete release ZIP before running this script.'
}
$taskTarget = Join-Path $env:LOCALAPPDATA 'Programs\KeepQuiet'
if (Get-Process -Name KeepQuiet -ErrorAction SilentlyContinue) {
    throw 'Close KeepQuiet before installing or updating its application files.'
}
New-Item -ItemType Directory -Force -Path $taskTarget | Out-Null
Copy-Item -Path (Join-Path $taskSource '*') -Destination $taskTarget -Recurse -Force
$taskShell = New-Object -ComObject WScript.Shell
$taskShortcut = $taskShell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'KeepQuiet.lnk'))
$taskShortcut.TargetPath = Join-Path $taskTarget 'KeepQuiet.exe'
$taskShortcut.WorkingDirectory = $taskTarget
$taskShortcut.Save()
Start-Process -FilePath (Join-Path $taskTarget 'KeepQuiet.exe') -WorkingDirectory $taskTarget
Write-Host 'KeepQuiet deployed. Driver installation is manual; update checks only notify.'
