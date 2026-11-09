param([string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskDist = [IO.Path]::GetFullPath((Join-Path $taskRoot $OutputDirectory))
if (-not $taskDist.StartsWith($taskRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Release output must stay inside the KeepQuiet workspace.'
}
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = (Get-Command python.exe).Source }
& $taskPython -B -m pytest -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; build stopped.' }
# Keep host-app PDF/image utility DLLs out of the Windows dependency scan.
$taskOriginalPath = $env:PATH
try {
    $env:PATH = ((Split-Path -Parent $taskPython), [Environment]::GetFolderPath('System'), $env:SystemRoot) -join ';'
    & $taskPython -m PyInstaller --noconfirm --clean --distpath $taskDist KeepQuiet.spec
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
} finally {
    $env:PATH = $taskOriginalPath
}
& $taskPython -B 'scripts\Prepare-QtSources.py' --output $taskDist
if ($LASTEXITCODE -ne 0) { throw 'Corresponding Qt/PySide source packaging failed.' }
Copy-Item -LiteralPath 'scripts\Install-KeepQuiet.ps1' -Destination (Join-Path $taskDist 'Install-KeepQuiet.ps1') -Force
Copy-Item -LiteralPath 'scripts\README-release.md' -Destination (Join-Path $taskDist 'README.md') -Force
Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination (Join-Path $taskDist 'THIRD_PARTY_NOTICES.md') -Force
Copy-Item -LiteralPath 'LICENSE' -Destination (Join-Path $taskDist 'LICENSE') -Force
Copy-Item -LiteralPath 'LICENSE_STATUS.md' -Destination (Join-Path $taskDist 'LICENSE_STATUS.md') -Force
Copy-Item -LiteralPath 'vendor\redistribution\QT_PYSIDE_NOTICE.md' -Destination (Join-Path $taskDist 'QT_PYSIDE_NOTICE.md') -Force
Copy-Item -LiteralPath 'vendor\redistribution\REBUILD_AND_REPLACE.md' -Destination (Join-Path $taskDist 'REBUILD_AND_REPLACE.md') -Force
$taskVersion = & $taskPython -c 'from keepquiet import __version__; print(__version__)'
$taskZip = Join-Path $taskDist "KeepQuiet-$taskVersion-win-x64.zip"
$taskFiles = @('KeepQuiet','Install-KeepQuiet.ps1','README.md','THIRD_PARTY_NOTICES.md','LICENSE_STATUS.md','LICENSE','QT_PYSIDE_NOTICE.md','REBUILD_AND_REPLACE.md') | ForEach-Object { Join-Path $taskDist $_ }
Compress-Archive -LiteralPath $taskFiles -DestinationPath $taskZip -Force
$taskSourceManifest = Get-Content -LiteralPath 'vendor\redistribution\qt-pyside-manifest.json' -Raw | ConvertFrom-Json
$taskReleaseZips = @($taskZip, (Join-Path $taskDist $taskSourceManifest.source_bundle))
$taskSums = foreach ($taskReleaseZip in $taskReleaseZips) {
    (Get-FileHash -LiteralPath $taskReleaseZip -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + [IO.Path]::GetFileName($taskReleaseZip)
}
$taskSums | Set-Content -LiteralPath (Join-Path $taskDist 'SHA256SUMS.txt') -Encoding ASCII
Write-Host "Build complete: $taskZip"
