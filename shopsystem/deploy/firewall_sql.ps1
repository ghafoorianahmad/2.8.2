<#
.SYNOPSIS
    Limit SQL Server (the accounting database) to this server and the
    accounting PCs - REQUIREMENTS §10, SECURITY.md §4.
.DESCRIPTION
    The vendor fixes the "sa" password, so the network is what keeps other
    computers away from the database. This script:
      1. finds the SQL Server instance program (sqlservr.exe) and SQL Browser;
      2. lists every enabled inbound ALLOW rule that already opens them
         (program rules, TCP 1433, UDP 1434) - Windows ORs allow rules, so a
         broad rule would make a narrow one pointless;
      3. with -Apply: disables those rules (never deletes them; their names are
         saved in sql_firewall_disabled.txt next to this script) and creates
         "ShopServer SQL (restricted)" + "ShopServer SQL Browser (restricted)"
         that allow only -AllowedIPs.
    Without -Apply nothing changes: it only prints what it would do.
    -Undo removes the two rules and enables the saved rules again.
    Connections from this computer itself are not filtered by the firewall,
    so the shop service keeps working.
.EXAMPLE
    .\firewall_sql.ps1 -Instance SAZEHHESAB -AllowedIPs 192.168.1.20,192.168.1.21
    .\firewall_sql.ps1 -Instance SAZEHHESAB -AllowedIPs 192.168.1.20,192.168.1.21 -Apply
    .\firewall_sql.ps1 -Undo
#>
[CmdletBinding()]
param(
    [string]$Instance = 'SAZEHHESAB',
    [string[]]$AllowedIPs = @(),
    [switch]$Apply,
    [switch]$Undo
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$RuleSql = 'ShopServer SQL (restricted)'
$RuleBrowser = 'ShopServer SQL Browser (restricted)'
$StateFile = Join-Path $PSScriptRoot 'sql_firewall_disabled.txt'

Assert-Admin

if ($Undo) {
    Remove-NetFirewallRule -DisplayName $RuleSql -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName $RuleBrowser -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $StateFile) {
        foreach ($name in Get-Content -LiteralPath $StateFile) {
            if ($name.Trim()) { Enable-NetFirewallRule -Name $name.Trim() -ErrorAction SilentlyContinue }
        }
        Remove-Item -LiteralPath $StateFile -Force
    }
    Write-Host 'Restored the previous SQL firewall rules.'
    exit 0
}

$ips = @($AllowedIPs | ForEach-Object { $_ -split '[,;\s]+' } | Where-Object { $_ })
if (-not $ips) { Write-Host 'Give the accounting PCs with -AllowedIPs (e.g. 192.168.1.20,192.168.1.21).'; exit 1 }
foreach ($ip in $ips) {
    if ($ip -notmatch '^[0-9a-fA-F:.]+(/\d{1,3})?$|^[0-9.]+-[0-9.]+$') { throw "Not an IP address, range or subnet: $ip" }
}

# ---- the instance program ------------------------------------------------------
$names = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL' -ErrorAction SilentlyContinue
$id = if ($names) { $names.$Instance } else { $null }
if (-not $id) { throw "SQL Server instance '$Instance' not found in the registry." }
$setup = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$id\Setup"
$sqlservr = Join-Path $setup.SQLBinRoot 'sqlservr.exe'
$browser = Join-Path ${env:ProgramFiles(x86)} 'Microsoft SQL Server\90\Shared\sqlbrowser.exe'
Write-Host "Instance $Instance -> $sqlservr"

# ---- rules that already open SQL --------------------------------------------------
$open = @()
foreach ($rule in Get-NetFirewallRule -Direction Inbound -Action Allow -Enabled True) {
    if ($rule.DisplayName -in @($RuleSql, $RuleBrowser)) { continue }
    $app = ($rule | Get-NetFirewallApplicationFilter).Program
    $port = $rule | Get-NetFirewallPortFilter
    $hit = ($app -and ($app -ieq $sqlservr -or $app -like '*\sqlservr.exe' -or $app -like '*\sqlbrowser.exe')) -or
           ($port.Protocol -eq 'TCP' -and @($port.LocalPort) -contains '1433') -or
           ($port.Protocol -eq 'UDP' -and @($port.LocalPort) -contains '1434')
    if ($hit) { $open += $rule }
}
if ($open) {
    Write-Host 'These enabled rules open SQL to everyone and would be DISABLED:'
    $open | ForEach-Object { Write-Host ("  - {0}  [{1}]" -f $_.DisplayName, $_.Name) }
} else {
    Write-Host 'No other rule opens SQL.'
}
Write-Host ("New rules would allow only: {0}" -f ($ips -join ', '))

if (-not $Apply) { Write-Host 'Dry run - nothing changed. Run again with -Apply.'; exit 0 }

$open | ForEach-Object { Add-Content -LiteralPath $StateFile -Value $_.Name; Disable-NetFirewallRule -Name $_.Name }
Remove-NetFirewallRule -DisplayName $RuleSql -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName $RuleBrowser -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $RuleSql -Direction Inbound -Action Allow -Protocol TCP `
    -Program $sqlservr -RemoteAddress $ips -Profile Any | Out-Null
if (Test-Path -LiteralPath $browser) {
    New-NetFirewallRule -DisplayName $RuleBrowser -Direction Inbound -Action Allow -Protocol UDP `
        -LocalPort 1434 -RemoteAddress $ips -Profile Any | Out-Null
}
Write-Host 'Done. Test the accounting program on each PC; to go back: .\firewall_sql.ps1 -Undo'
exit 0
