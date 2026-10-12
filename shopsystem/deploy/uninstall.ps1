<#
.SYNOPSIS
    Remove the ShopServer service, its firewall rule and (optionally) the program.
.DESCRIPTION
    The data folder (%ProgramData%\ShopServer: .env, databases, receipts,
    backups) is NEVER deleted by this script. Delete it by hand only after you
    have a copy.
.EXAMPLE
    .\uninstall.ps1                 # service + firewall rule
    .\uninstall.ps1 -RemoveProgram  # also the program folder
#>
[CmdletBinding()]
param([switch]$RemoveProgram)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Admin

$svc = Get-ShopService
if (-not $svc) { Write-Host 'The ShopServer service is not installed.'; exit 0 }
$script:LogFile = Join-Path $svc.DataDir 'install.log'
Write-Log 'uninstall started'
Stop-ShopService $svc.InstallDir
if (Test-Path -LiteralPath $svc.Exe) {
    $result = Invoke-ShopSystem $svc.Exe @('--uninstall-service', '--data-dir', $svc.DataDir)
    if ($result.Code -ne 0) { throw 'Removing the service failed.' }
} elseif (-not $script:Fake) {
    & sc.exe delete $script:ServiceName | Out-Null
}
if (-not $script:Fake) { & netsh advfirewall firewall delete rule "name=$script:FirewallRule" | Out-Null }
Write-Log 'service and firewall rule removed'
if ($RemoveProgram -and (Test-Path -LiteralPath $svc.InstallDir)) {
    Remove-Item -LiteralPath $svc.InstallDir -Recurse -Force
    Write-Log "program folder removed: $($svc.InstallDir)"
}
Write-Host ''
Write-Host "Data kept in $($svc.DataDir) (configuration, databases, receipts, backups)."
exit 0
