<#
.SYNOPSIS
    Install the shop server as the Windows service "ShopServer".
.DESCRIPTION
    Copies ShopSystem\ to the program folder, locks the data folder to SYSTEM and
    Administrators, registers the service (virtual account NT SERVICE\ShopServer,
    automatic start at boot, restart on failure), opens the API port to the LAN
    only, and starts it when a .env exists.

    The normal first install is ShopServerSetup.exe (it also creates .env and the
    first manager). Use this script for a server without the installer, or to
    move an older "scheduled task" installation to the service.
.PARAMETER AllowedIPs
    Optional list of client addresses/subnets (e.g. "192.168.10.0/24,192.168.10.5").
    Default: the local subnet. Saved in .env as FIREWALL_ALLOWED_IPS.
.EXAMPLE
    .\install.ps1
    .\install.ps1 -AllowedIPs 192.168.20.0/24
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:ProgramFiles 'ShopServer\ShopSystem'),
    [string]$DataDir = (Join-Path $env:ProgramData 'ShopServer'),
    [string]$AllowedIPs = $null,
    [int]$HealthTimeout = 120
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Admin

if (Get-ShopService) {
    Write-Host 'The ShopServer service is already installed. Use update.ps1 to install a new version.'
    exit 1
}
$source = Join-Path $PSScriptRoot 'ShopSystem'
if (-not (Test-Path -LiteralPath (Join-Path $source 'ShopSystem.exe'))) { throw "ShopSystem.exe not found in $source" }

# ---- data folder: SYSTEM + Administrators only (by SID); the service gets its grant below
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
& icacls $DataDir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /C /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not restrict $DataDir" }
$script:LogFile = Join-Path $DataDir 'install.log'
Write-Log "install started (program: $InstallDir, data: $DataDir)"

# ---- program
if (Test-Path -LiteralPath $InstallDir) {
    Write-Log 'program folder exists - replacing it'
    Get-Process -Name ShopSystem -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $InstallDir) | Out-Null
Copy-Item -LiteralPath $source -Destination $InstallDir -Recurse -Force
$exe = Join-Path $InstallDir 'ShopSystem.exe'

# ---- service (also removes the old boot task, grants NT SERVICE\ShopServer)
$result = Invoke-ShopSystem $exe @('--install-service', '--data-dir', $DataDir)
if ($result.Code -ne 0) {
    $why = if ($result.Json) { $result.Json.message } else { 'no answer' }
    throw "Service registration failed: $why"
}
Write-Log ("service registered (account: {0}; old task removed: {1})" -f $result.Json.account, $result.Json.legacy_task_removed)

# ---- firewall: the API port from .env, LAN only
$envFile = Join-Path $DataDir '.env'
$port = Read-EnvValue $envFile 'API_PORT'
if (-not $port) { $port = '8443' }
if ($null -eq $AllowedIPs -or $AllowedIPs -eq '') { $AllowedIPs = Read-EnvValue $envFile 'FIREWALL_ALLOWED_IPS' }
$remote = Set-ShopFirewall $exe ([int]$port) $AllowedIPs
Write-Log "firewall: TCP $port from $remote (private/domain profiles)"
if ($AllowedIPs -and (Test-Path -LiteralPath $envFile) -and -not (Read-EnvValue $envFile 'FIREWALL_ALLOWED_IPS')) {
    Add-Content -LiteralPath $envFile -Value "FIREWALL_ALLOWED_IPS=$AllowedIPs" -Encoding UTF8
}

if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Log 'no .env yet - the service is installed but NOT started.'
    Write-Host ''
    Write-Host "Next: run the server setup (ShopAdmin.exe --server-setup) or create $envFile"
    Write-Host '      from ShopSystem\.env.example, then:  Start-Service ShopServer'
    exit 0
}
Start-ShopService
$svc = Get-ShopService
if (Test-ShopHealth $svc $HealthTimeout) { Write-Log 'INSTALL OK - the server answers /health'; exit 0 }
Write-Log 'installed, but the server does not answer yet - see app.log and supervisor.log in the data folder'
exit 2
