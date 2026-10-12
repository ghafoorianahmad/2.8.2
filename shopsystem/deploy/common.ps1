# Shared helpers for install.ps1 / update.ps1 / uninstall.ps1 (dot-sourced).
#
# Test mode: when $env:SHOP_DEPLOY_FAKE names a folder, nothing on the system is
# touched. The service lives in files there (pathname.txt, state.txt) and the
# health check reads fake_health.txt from the program folder. Used by
# shopsystem/tests/test_deploy.py only.

$script:ServiceName = 'ShopServer'
$script:FirewallRule = 'ShopServer'
$script:Fake = $env:SHOP_DEPLOY_FAKE
$script:LogFile = $null

function Write-Log([string]$Message) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    if ($script:LogFile) {
        try { Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8 } catch { }
    }
}

function Assert-Admin {
    if ($script:Fake) { return }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this script from an elevated PowerShell (Run as administrator).'
    }
}

function Split-ServicePath([string]$PathName) {
    # "C:\...\ShopSystem.exe" --winservice --data-dir C:\ProgramData\ShopServer
    if ($PathName -match '^\s*"([^"]+)"\s*(.*)$') { $exe = $Matches[1]; $rest = $Matches[2] }
    elseif ($PathName -match '^\s*(\S+)\s*(.*)$') { $exe = $Matches[1]; $rest = $Matches[2] }
    else { return $null }
    $data = Join-Path $env:ProgramData 'ShopServer'
    if ($rest -match '--data-dir\s+"([^"]+)"') { $data = $Matches[1] }
    elseif ($rest -match '--data-dir\s+(\S+)') { $data = $Matches[1] }
    return [pscustomobject]@{ Exe = $exe; InstallDir = (Split-Path -Parent $exe); DataDir = $data }
}

function Get-ShopService {
    if ($script:Fake) {
        $file = Join-Path $script:Fake 'pathname.txt'
        if (-not (Test-Path -LiteralPath $file)) { return $null }
        return Split-ServicePath (Get-Content -LiteralPath $file -Raw).Trim()
    }
    $svc = Get-CimInstance Win32_Service -Filter "Name='$script:ServiceName'" -ErrorAction SilentlyContinue
    if (-not $svc) { return $null }
    return Split-ServicePath $svc.PathName
}

function Get-ShopServiceState {
    if ($script:Fake) {
        $file = Join-Path $script:Fake 'state.txt'
        if (Test-Path -LiteralPath $file) { return (Get-Content -LiteralPath $file -Raw).Trim() }
        return 'Stopped'
    }
    $svc = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
    if ($svc) { return [string]$svc.Status }
    return $null
}

function Stop-ShopService([string]$InstallDir) {
    if ($script:Fake) {
        Set-Content -LiteralPath (Join-Path $script:Fake 'state.txt') -Value 'Stopped'
        Add-Content -LiteralPath (Join-Path $script:Fake 'calls.txt') -Value 'stop'
        return
    }
    $svc = Get-Service -Name $script:ServiceName -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne 'Stopped') {
        Stop-Service -Name $script:ServiceName -Force -ErrorAction Stop
        $svc.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60))
    }
    # leftovers of this install (a worker that did not exit in time)
    if ($InstallDir) {
        Get-Process -Name ShopSystem -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) } |
            Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

function Start-ShopService {
    if ($script:Fake) {
        Set-Content -LiteralPath (Join-Path $script:Fake 'state.txt') -Value 'Running'
        Add-Content -LiteralPath (Join-Path $script:Fake 'calls.txt') -Value 'start'
        # a started "version" may change data (e.g. a database migration)
        $svc = Get-ShopService
        $hook = Join-Path $svc.InstallDir 'fake_start.ps1'
        if (Test-Path -LiteralPath $hook) { & $hook $svc.DataDir }
        return
    }
    Start-Service -Name $script:ServiceName -ErrorAction Stop
}

function Invoke-ShopSystem([string]$Exe, [string[]]$Arguments) {
    # Runs ShopSystem.exe and returns @{ Code; Json } (it prints one JSON line).
    # Test mode: SHOP_DEPLOY_FAKE_PY = "<python.exe>|<launcher.py>" runs the real
    # launcher code instead of the fake exe (backup / restore tests).
    if ($script:Fake -and $env:SHOP_DEPLOY_FAKE_PY) {
        $py, $launcher = $env:SHOP_DEPLOY_FAKE_PY -split '\|', 2
        $output = & $py $launcher @Arguments 2>$null
    } else {
        $output = & $Exe @Arguments 2>$null
    }
    $code = $LASTEXITCODE
    $json = $null
    foreach ($line in @($output)) {
        $text = [string]$line
        if ($text.TrimStart().StartsWith('{')) {
            try { $json = $text | ConvertFrom-Json } catch { }
        }
    }
    return [pscustomobject]@{ Code = $code; Json = $json }
}

function Test-ShopHealth($Service, [int]$Timeout) {
    if ($script:Fake) {
        $flag = Join-Path $Service.InstallDir 'fake_health.txt'
        return ((Test-Path -LiteralPath $flag) -and ((Get-Content -LiteralPath $flag -Raw).Trim() -eq 'ok'))
    }
    $result = Invoke-ShopSystem $Service.Exe @('--health-check', '--timeout', "$Timeout", '--data-dir', $Service.DataDir)
    if ($result.Code -ne 0 -and $result.Json) { Write-Log ("health check: {0}" -f $result.Json.error) }
    return ($result.Code -eq 0)
}

function Move-Folder([string]$From, [string]$To) {
    # Move-Item cannot move a folder to another drive: copy + delete then.
    $sameRoot = ([IO.Path]::GetPathRoot($From) -eq [IO.Path]::GetPathRoot($To))
    if ($sameRoot) { Move-Item -LiteralPath $From -Destination $To -ErrorAction Stop; return }
    Copy-Item -LiteralPath $From -Destination $To -Recurse -Force -ErrorAction Stop
    Remove-Item -LiteralPath $From -Recurse -Force -ErrorAction Stop
}

# What a backup of the data folder holds (never the backups folder itself, never logs).
# A SQLite write-ahead log can hold committed data (e.g. after a crash): it travels
# with its database, and a stale one is removed when a database is put back.
$script:DataFiles = @('.env', 'shopapi.db', 'shopbots.db', 'messages.fa.json',
                      'shopapi.db-wal', 'shopapi.db-shm', 'shopbots.db-wal', 'shopbots.db-shm')
$script:DataDirs = @('receipts', 'pricelists', 'tls')

function Backup-ShopData([string]$DataDir, [string]$Target) {
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    foreach ($name in $script:DataFiles) {
        $source = Join-Path $DataDir $name
        if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $Target -Force -ErrorAction Stop }
    }
    foreach ($name in $script:DataDirs) {
        $source = Join-Path $DataDir $name
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $Target $name) -Recurse -Force -ErrorAction Stop
        }
    }
}

function Restore-ShopData([string]$Source, [string]$DataDir) {
    foreach ($name in $script:DataFiles) {
        $saved = Join-Path $Source $name
        $live = Join-Path $DataDir $name
        if (Test-Path -LiteralPath $saved) { Copy-Item -LiteralPath $saved -Destination $live -Force -ErrorAction Stop }
        elseif (Test-Path -LiteralPath $live) { Remove-Item -LiteralPath $live -Force }
    }
    foreach ($name in $script:DataDirs) {
        $saved = Join-Path $Source $name
        $live = Join-Path $DataDir $name
        if (Test-Path -LiteralPath $live) { Remove-Item -LiteralPath $live -Recurse -Force }
        if (Test-Path -LiteralPath $saved) { Copy-Item -LiteralPath $saved -Destination $live -Recurse -Force -ErrorAction Stop }
    }
}

function Read-EnvValue([string]$EnvFile, [string]$Key) {
    if (-not (Test-Path -LiteralPath $EnvFile)) { return '' }
    foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
        if ($line -match ('^\s*' + [regex]::Escape($Key) + '\s*=\s*(.*)$')) {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ''
}

function Set-ShopFirewall([string]$Exe, [int]$Port, [string]$AllowedIPs) {
    # LAN only: the shop PCs' subnet by default, or an explicit list of addresses.
    $remote = 'localsubnet'
    if ($AllowedIPs -and $AllowedIPs.Trim()) {
        $parts = @($AllowedIPs -split '[,;\s]+' | Where-Object { $_ })
        foreach ($p in $parts) {
            if ($p -notmatch '^(?i:localsubnet|[0-9a-f:.]+(/\d{1,3})?|[0-9.]+-[0-9.]+)$') {
                throw "Not an IP address, range or subnet: $p"
            }
        }
        $remote = $parts -join ','
    }
    if ($script:Fake) {
        Set-Content -LiteralPath (Join-Path $script:Fake 'firewall.txt') -Value "$Port $remote"
        return $remote
    }
    & netsh advfirewall firewall delete rule "name=$script:FirewallRule" | Out-Null
    & netsh advfirewall firewall add rule "name=$script:FirewallRule" dir=in action=allow protocol=TCP `
        "localport=$Port" "remoteip=$remote" profile=private,domain "program=$Exe" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'The Windows Firewall rule could not be created.' }
    return $remote
}
