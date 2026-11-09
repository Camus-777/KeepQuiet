param(
    [Parameter(Mandatory=$true)][string]$Package,
    [Parameter(Mandatory=$true)][string]$ExpectedSha256,
    [Parameter(Mandatory=$true)][string]$ResultPath,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$taskStage = $null
try {
    $actualHash = (Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash
    if ($actualHash -ne $ExpectedSha256) { throw 'VB-CABLE package hash mismatch.' }
    $taskStage = Join-Path ([IO.Path]::GetTempPath()) ('KeepQuiet-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $taskStage | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($Package)
    try {
        foreach ($entry in $archive.Entries) {
            if ($entry.FullName -match '[/\\:]' -or $entry.FullName -eq '..') {
                throw 'Unexpected archive path.'
            }
        }
    } finally { $archive.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($Package, $taskStage)
    $setup = Join-Path $taskStage 'VBCABLE_Setup_x64.exe'
    $cat = Join-Path $taskStage 'vbaudio_cable64_win10.cat'
    $signed = Get-AuthenticodeSignature -LiteralPath $setup
    if ($signed.Status -ne 'Valid' -or $signed.SignerCertificate.Subject -notmatch 'BUREL VINCENT') {
        throw 'VB-CABLE setup Authenticode publisher verification failed.'
    }
    $catalog = Get-AuthenticodeSignature -LiteralPath $cat
    if ($catalog.Status -ne 'Valid' -or $catalog.SignerCertificate.Subject -notmatch 'Microsoft Windows Hardware Compatibility') {
        throw 'VB-CABLE Windows driver catalog verification failed.'
    }
    if ($VerifyOnly) {
        $result = @{ state='verified'; publisher=$signed.SignerCertificate.Subject; sha256=$actualHash }
    } else {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            throw 'Driver installation requires Windows UAC elevation.'
        }
        $existing = @(Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceName -eq 'VB-Audio Virtual Cable' })
        if ($existing.Count -gt 0) {
            # An in-place driver-store update preserves the existing root device.
            # Never uninstall a shared cable just to try a new version.
            $inf = Join-Path $taskStage 'vbMmeCable64_win10.inf'
            $pnpLog = & "$env:SystemRoot\System32\pnputil.exe" /add-driver $inf /install 2>&1
            $code = $LASTEXITCODE
            if ($code -ne 0 -and $code -ne 3010) { throw "PnP update failed ($code): $pnpLog" }
        } else {
            $proc = Start-Process -FilePath $setup -ArgumentList '-i','-h' -WorkingDirectory $taskStage -WindowStyle Hidden -Wait -PassThru
            $code = $proc.ExitCode
            # VB setup uses its own exit codes. Verify actual PnP state instead
            # of assuming a zero return proves that the device was installed.
        }
        Start-Sleep -Seconds 2
        $now = @(Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceName -eq 'VB-Audio Virtual Cable' })
        $infText = Get-Content -LiteralPath (Join-Path $taskStage 'vbMmeCable64_win10.inf') -Raw
        $expectedVersion = [regex]::Match($infText, 'DriverVer\s*=\s*[\d/]+\s*,\s*([\d.]+)').Groups[1].Value
        $matched = @($now | Where-Object { [version]$_.DriverVersion -ge [version]$expectedVersion }).Count -gt 0
        if (-not $matched -and $existing.Count -gt 0 -and $code -ne 3010) {
            throw 'Windows did not select the new driver. Existing driver was retained; use the official installer to resolve its ranking.'
        }
        $result = @{ state='reboot_required'; exit_code=$code; driver_verified=$matched; expected_version=$expectedVersion }
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    exit 0
} catch {
    @{ state='error'; error=$_.Exception.Message } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath -Encoding UTF8
    exit 1
} finally {
    # Delete only the exact task-specific directory created above.
    if ($taskStage -and (Test-Path -LiteralPath $taskStage)) {
        $taskFull = [IO.Path]::GetFullPath($taskStage)
        $tempFull = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if ($taskFull.StartsWith($tempFull, [StringComparison]::OrdinalIgnoreCase) -and
            [IO.Path]::GetFileName($taskFull).StartsWith('KeepQuiet-')) {
            Remove-Item -LiteralPath $taskFull -Recurse -Force
        }
    }
}
