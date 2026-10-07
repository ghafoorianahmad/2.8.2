<#
.SYNOPSIS
    Store the Telegram bot token (and optionally the proxy and admin chat ids)
    in the ShopServer .env - without ever showing the token.

.DESCRIPTION
    * The token is typed into a hidden prompt (like a password). It is never
      printed, logged, put on a command line or written anywhere except .env.
    * Only C:\ProgramData\ShopServer\.env is changed, in place: the file keeps
      its existing permissions (no icacls, no new file, no backup copy).
    * Other keys in .env are kept as they are.
    * The ShopServer task is NOT restarted. Restart it yourself afterwards:
          schtasks /End /TN ShopServer ; schtasks /Run /TN ShopServer

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\set_telegram_token.ps1
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\set_telegram_token.ps1 -Proxy socks5://127.0.0.1:10808 -AdminChatIds telegram:123456789
#>
[CmdletBinding()]
param(
    [string]$EnvFile = (Join-Path $env:ProgramData "ShopServer\.env"),
    [string]$Proxy,          # e.g. socks5://127.0.0.1:10808 ; "none" clears it
    [string]$AdminChatIds,   # e.g. telegram:123456789 ; comma separated
    [switch]$KeepToken       # change only proxy / admin ids
)

$ErrorActionPreference = "Stop"

function Fail([string]$message) {
    Write-Host ""
    Write-Host "[ERROR] $message" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    Fail "$EnvFile not found. Run the server setup (ShopAdmin --server-setup) first."
}

# ---- read the current file (values stay in memory only) -------------------
try {
    $raw = [IO.File]::ReadAllText($EnvFile)
} catch [UnauthorizedAccessException] {
    Fail "No permission to read $EnvFile. Run this as the Windows account that runs the ShopServer task, or as Administrator."
}
$newline = if ($raw -match "`r`n") { "`r`n" } else { "`n" }
$lines = New-Object System.Collections.Generic.List[string]
if ($raw.Length -gt 0) {
    foreach ($l in ($raw -split "`r?`n")) { $lines.Add($l) }
    if ($lines.Count -gt 0 -and $lines[$lines.Count - 1] -eq "") { $lines.RemoveAt($lines.Count - 1) }
}

function Get-EnvValue([string]$key) {
    foreach ($l in $lines) {
        if ($l -match "^\s*$([regex]::Escape($key))\s*=(.*)$") { return $Matches[1].Trim() }
    }
    return ""
}

function Set-EnvValue([string]$key, [string]$value) {
    if ($value -match "[`r`n`0]") { Fail "$key must be a single line." }
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$([regex]::Escape($key))\s*=") {
            $lines[$i] = "$key=$value"
            return
        }
    }
    $lines.Add("$key=$value")
}

Write-Host "ShopServer - Telegram settings"
Write-Host "  file: $EnvFile"
Write-Host ""

# ---- 1) token (hidden) ------------------------------------------------------
$changed = @()
if (-not $KeepToken) {
    $secure = Read-Host -Prompt "Paste the Telegram bot token from BotFather (input is hidden)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim()
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    if ($token -eq "") { Fail "No token entered - nothing changed." }
    if ($token -notmatch '^\d{5,15}:[A-Za-z0-9_-]{30,64}$') {
        $token = $null
        Fail "That does not look like a bot token (expected 123456789:ABC...). Nothing changed."
    }
    Set-EnvValue "TELEGRAM_TOKEN" $token
    $token = $null
    $changed += "TELEGRAM_TOKEN (hidden)"
}

# ---- 2) proxy -----------------------------------------------------------------
$currentProxy = Get-EnvValue "TELEGRAM_PROXY"
if (-not $currentProxy) { $currentProxy = Get-EnvValue "PROXY_URL" }
if (-not $PSBoundParameters.ContainsKey("Proxy")) {
    $suggest = if ($currentProxy) { $currentProxy } else { "socks5://127.0.0.1:10808" }
    $answer = Read-Host -Prompt "Telegram proxy [Enter = $suggest, 'none' = no proxy]"
    $Proxy = if ($answer.Trim()) { $answer.Trim() } else { $suggest }
}
if ($Proxy -eq "none") { $Proxy = "" }
if ($Proxy -and $Proxy -notmatch '^(socks5h?|http|https)://[^\s/]+:\d{1,5}/?$') {
    Fail "Proxy must look like socks5://127.0.0.1:10808 or http://127.0.0.1:10808. Nothing changed."
}
if ($Proxy -ne (Get-EnvValue "TELEGRAM_PROXY")) {
    Set-EnvValue "TELEGRAM_PROXY" $Proxy
    $changed += "TELEGRAM_PROXY=" + $(if ($Proxy) { $Proxy } else { "(empty)" })
}

# ---- 3) admin chat ids (optional) ---------------------------------------------
$currentAdmins = Get-EnvValue "ADMIN_CHAT_IDS"
if (-not $PSBoundParameters.ContainsKey("AdminChatIds")) {
    $hint = if ($currentAdmins) { "Enter = keep '$currentAdmins'" } else { "Enter = skip; get your id later with /myid" }
    $AdminChatIds = (Read-Host -Prompt "Admin chat ids, e.g. telegram:123456789 [$hint]").Trim()
    if (-not $AdminChatIds) { $AdminChatIds = $currentAdmins }
}
$AdminChatIds = ($AdminChatIds -replace "\s", "")
if ($AdminChatIds -and $AdminChatIds -notmatch '^((telegram|bale):)?-?\d{3,20}(,((telegram|bale):)?-?\d{3,20})*$') {
    Fail "Admin chat ids must look like telegram:123456789 (comma separated). Nothing changed."
}
if ($AdminChatIds -ne $currentAdmins) {
    Set-EnvValue "ADMIN_CHAT_IDS" $AdminChatIds
    $changed += "ADMIN_CHAT_IDS=$AdminChatIds"
}

if ($changed.Count -eq 0) {
    Write-Host "Nothing to change."
    exit 0
}

# ---- write in place: same file object, so its ACL stays exactly as it was ---
$aclBefore = (Get-Acl -LiteralPath $EnvFile).Sddl
$content = ($lines -join $newline) + $newline
try {
    [IO.File]::WriteAllText($EnvFile, $content, (New-Object System.Text.UTF8Encoding($false)))
} catch [UnauthorizedAccessException] {
    Fail "No permission to write $EnvFile. Run as the account that runs the ShopServer task, or as Administrator."
} finally {
    $content = $null
    $lines.Clear()
}
$aclAfter = (Get-Acl -LiteralPath $EnvFile).Sddl

Write-Host ""
Write-Host "Saved:" -ForegroundColor Green
foreach ($c in $changed) { Write-Host "  - $c" }
if ($aclBefore -eq $aclAfter) {
    Write-Host "  permissions of .env: unchanged"
} else {
    Write-Host "  WARNING: permissions of .env changed - check with: icacls `"$EnvFile`"" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Next:"
Write-Host "  1) test:    powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\test_telegram_proxy.ps1`""
Write-Host "  2) restart: schtasks /End /TN ShopServer ; schtasks /Run /TN ShopServer"
