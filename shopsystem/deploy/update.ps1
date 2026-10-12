<#
.SYNOPSIS
    Update the shop server to a new version, with automatic rollback.
.DESCRIPTION
    1. Stops the ShopServer service.
    2. Backs up the program folder and the data (.env, databases, bot texts,
       receipts, price-list PDFs, TLS certificate) to
       %ProgramData%\ShopServer\backups\update_<time>\.
    3. Puts the new program folder in place and starts the service.
    4. Waits for the server to answer /health. If it does not, it puts the old
       program and data back, starts the old version and says so.
    The last 3 update backups are kept.
    Exit codes: 0 updated, 3 rolled back (old version running), 4 rolled back
    but the old version is not healthy either, 1 error before anything changed.
.EXAMPLE
    # from the extracted package folder, in an elevated PowerShell:
    .\update.ps1
    .\update.ps1 -Package D:\ShopServer_2.1.0.zip
#>
[CmdletBinding()]
param(
    [string]$Package = $PSScriptRoot,
    [int]$HealthTimeout = 120,
    [int]$KeepBackups = 3
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

Assert-Admin
$svc = Get-ShopService
if (-not $svc) { Write-Host 'The ShopServer service is not installed - use install.ps1.'; exit 1 }

# ---- the new version ---------------------------------------------------------
$extracted = $null
if ($Package -like '*.zip') {
    $extracted = Join-Path ([IO.Path]::GetTempPath()) ('shopserver_update_' + [guid]::NewGuid().ToString('N'))
    Expand-Archive -LiteralPath $Package -DestinationPath $extracted
    $Package = $extracted
}
$newProgram = Join-Path $Package 'ShopSystem'
if (-not (Test-Path -LiteralPath (Join-Path $newProgram 'ShopSystem.exe'))) {
    Write-Host "ShopSystem\ShopSystem.exe not found in $Package"; exit 1
}
if ([IO.Path]::GetFullPath($newProgram).TrimEnd('\') -eq [IO.Path]::GetFullPath($svc.InstallDir).TrimEnd('\')) {
    Write-Host 'The package folder is the installed folder - extract the package somewhere else.'; exit 1
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$backupRoot = Join-Path $svc.DataDir 'backups'
$backup = Join-Path $backupRoot "update_$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
$script:LogFile = Join-Path $svc.DataDir 'update.log'
$version = ''
$versionFile = Join-Path $Package 'VERSION.txt'
if (Test-Path -LiteralPath $versionFile) { $version = (Get-Content -LiteralPath $versionFile -Raw).Trim() }
Write-Log "update started (new version: $version, program: $($svc.InstallDir))"

$staging = $svc.InstallDir.TrimEnd('\') + '.new'
$programBackup = Join-Path $backup 'program'
$dataBackup = Join-Path $backup 'data'
$swapped = $false
$ok = $false
try {
    Stop-ShopService $svc.InstallDir
    Write-Log 'service stopped'
    Backup-ShopData $svc.DataDir $dataBackup
    Write-Log "data backed up to $dataBackup"
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    Copy-Item -LiteralPath $newProgram -Destination $staging -Recurse -Force
    Move-Folder $svc.InstallDir $programBackup
    $swapped = $true
    Move-Folder $staging $svc.InstallDir
    Write-Log 'new program in place; starting'
    Start-ShopService
    $ok = Test-ShopHealth $svc $HealthTimeout
    if (-not $ok) { Write-Log 'the new version did not become healthy' }
} catch {
    Write-Log ("update failed: {0}" -f $_.Exception.Message)
    $ok = $false
}

if ($ok) {
    Write-Log 'UPDATE OK'
    # keep only the newest backups
    Get-ChildItem -LiteralPath $backupRoot -Directory -Filter 'update_*' |
        Sort-Object Name -Descending | Select-Object -Skip $KeepBackups |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
    if ($extracted) { Remove-Item -LiteralPath $extracted -Recurse -Force -ErrorAction SilentlyContinue }
    exit 0
}

# ---- rollback ---------------------------------------------------------------------
Write-Log 'ROLLING BACK to the previous version'
try { Stop-ShopService $svc.InstallDir } catch { Write-Log ("stop during rollback: {0}" -f $_.Exception.Message) }
try {
    if ($swapped) {
        if (Test-Path -LiteralPath $svc.InstallDir) { Move-Folder $svc.InstallDir (Join-Path $backup 'failed_program') }
        Move-Folder $programBackup $svc.InstallDir
    }
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $dataBackup) { Restore-ShopData $dataBackup $svc.DataDir }
    Start-ShopService
} catch {
    Write-Log ("ROLLBACK FAILED: {0} - restore by hand from $backup" -f $_.Exception.Message)
    exit 4
}
if (Test-ShopHealth $svc $HealthTimeout) {
    Write-Log 'ROLLED BACK - the previous version is running again'
    exit 3
}
Write-Log "ROLLED BACK but the previous version is not healthy either - see app.log; backup: $backup"
exit 4
