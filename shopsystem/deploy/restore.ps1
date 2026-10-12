<#
.SYNOPSIS
    Put a shop server backup back (daily .zip, or the encrypted off-server .ssbk).
.DESCRIPTION
    1. Restore test first: the backup is decrypted (if .ssbk) and checked
       (SHA-256 of every file, SQLite integrity, row counts). A bad backup is
       rejected before anything changes.
    2. Stops the ShopServer service and copies the current data to
       <data>\backups\pre_restore_<time>\ (safety copy).
    3. Puts the backup in place (.env, databases, bot texts, receipts,
       price-list PDFs, TLS certificate) and starts the service.
    4. Waits for /health. If it does not come, the safety copy goes back.
    The passphrase of a .ssbk is asked for (hidden) and never written anywhere.
    The Telegram worker session is never in a backup: after a restore on a new
    computer, log the shop's Telegram account in again (shoptg\login.ps1).
    Exit codes: 0 restored, 1 nothing changed (bad backup / wrong passphrase /
    not installed), 3 restore failed and the previous data is running again,
    4 restore failed and the previous data is not healthy either.
.EXAMPLE
    .\restore.ps1 -Backup C:\ProgramData\ShopServer\backups\daily\ShopServer_20261012_030000.zip
    .\restore.ps1 -Backup E:\ShopBackup\ShopServer_20261012_030000.ssbk
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Backup,
    [int]$HealthTimeout = 120
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

Assert-Admin
$svc = Get-ShopService
if (-not $svc) {
    Write-Host 'The ShopServer service is not installed. On a new computer: run install.ps1 (or ShopServerSetup) first, then this script.'
    exit 1
}
if (-not (Test-Path -LiteralPath $Backup)) { Write-Host "Backup not found: $Backup"; exit 1 }
$Backup = (Resolve-Path -LiteralPath $Backup).Path
$dataDir = $svc.DataDir
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$script:LogFile = Join-Path $dataDir 'restore.log'

$setPassphrase = $false
if ($Backup -like '*.ssbk' -and -not $env:SHOPSERVER_BACKUP_PASSPHRASE) {
    $secure = Read-Host 'Backup passphrase (from your paper)' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $env:SHOPSERVER_BACKUP_PASSPHRASE = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    $setPassphrase = $true
}

try {
    Write-Log "restore requested: $Backup"
    # ---- 1. restore test before anything changes -----------------------------
    $check = Invoke-ShopSystem $svc.Exe @('--verify-backup', $Backup, '--data-dir', $dataDir)
    if ($check.Code -ne 0 -or -not $check.Json -or -not $check.Json.ok) {
        $why = if ($check.Json) { "$($check.Json.error) $($check.Json.message)" } else { 'no answer' }
        Write-Log "backup rejected, nothing changed: $why"
        exit 1
    }
    Write-Log ("backup OK: {0} files, made {1}" -f $check.Json.files, $check.Json.created)

    # ---- 2. stop + safety copy -------------------------------------------------
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
    $safety = Join-Path $dataDir "backups\pre_restore_$stamp"
    Stop-ShopService $svc.InstallDir
    Write-Log 'service stopped'
    Backup-ShopData $dataDir $safety
    Write-Log "current data saved to $safety"

    # ---- 3. restore + start ----------------------------------------------------
    $ok = $false
    try {
        $result = Invoke-ShopSystem $svc.Exe @('--restore-backup', $Backup, '--data-dir', $dataDir)
        if ($result.Code -ne 0) {
            $why = if ($result.Json) { "$($result.Json.error) $($result.Json.message)" } else { 'no answer' }
            throw "restore failed: $why"
        }
        Write-Log 'backup put in place; starting'
        Start-ShopService
        $ok = Test-ShopHealth $svc $HealthTimeout
        if (-not $ok) { Write-Log 'the restored server did not become healthy' }
    } catch {
        Write-Log $_.Exception.Message
        $ok = $false
    }
    if ($ok) {
        Write-Log 'RESTORE OK'
        Write-Host 'Restored. If this is a new computer: log the Telegram worker in again (shoptg\login.ps1),'
        Write-Host 'and check that the ShopAdmin PCs still accept the server fingerprint.'
        exit 0
    }

    # ---- 4. put the previous data back ----------------------------------------
    Write-Log 'PUTTING THE PREVIOUS DATA BACK'
    try {
        Stop-ShopService $svc.InstallDir
        Restore-ShopData $safety $dataDir
        Start-ShopService
    } catch {
        Write-Log ("ROLLBACK FAILED: {0} - the previous data is in $safety" -f $_.Exception.Message)
        exit 4
    }
    if (Test-ShopHealth $svc $HealthTimeout) { Write-Log 'previous data running again'; exit 3 }
    Write-Log "previous data back but not healthy - see app.log; copy: $safety"
    exit 4
} finally {
    if ($setPassphrase) { Remove-Item Env:\SHOPSERVER_BACKUP_PASSPHRASE -ErrorAction SilentlyContinue }
}
