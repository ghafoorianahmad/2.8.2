<#
.SYNOPSIS
    Check that Telegram is reachable through the local proxy and that the bot
    token works (getMe) - without printing the token.

.DESCRIPTION
    Proxy order: -Proxy, else TELEGRAM_PROXY / PROXY_URL from .env, else it
    auto-detects socks5://127.0.0.1:10808 and then http://127.0.0.1:10808 and
    tells you which one works (-Save writes it to .env as TELEGRAM_PROXY).

    The token is read from .env and handed to curl.exe through stdin (never on
    the command line, never on screen). Without a token only the proxy is tested.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\test_telegram_proxy.ps1
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\test_telegram_proxy.ps1 -Detect -Save
#>
[CmdletBinding()]
param(
    [string]$EnvFile = (Join-Path $env:ProgramData "ShopServer\.env"),
    [string]$Proxy,
    [string]$HostPort = "127.0.0.1:10808",
    [switch]$Detect,      # ignore the configured proxy and try socks5 then http
    [switch]$Save,        # write the working proxy to .env (TELEGRAM_PROXY)
    [int]$TimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"
$curl = Join-Path $env:SystemRoot "System32\curl.exe"
if (-not (Test-Path $curl)) { Write-Host "[ERROR] curl.exe not found ($curl)." -ForegroundColor Red; exit 1 }

function Read-EnvValue([string]$key) {
    if (-not (Test-Path -LiteralPath $EnvFile)) { return "" }
    try { $text = [IO.File]::ReadAllText($EnvFile) } catch { return "" }
    foreach ($l in ($text -split "`r?`n")) {
        if ($l -match "^\s*$([regex]::Escape($key))\s*=(.*)$") { return $Matches[1].Trim() }
    }
    return ""
}

# curl exit codes worth explaining
$CurlErrors = @{
    5  = "proxy host could not be resolved"
    7  = "could not connect (proxy not running on that port?)"
    28 = "timeout"
    35 = "TLS handshake failed"
    56 = "connection closed by the proxy"
    97 = "proxy handshake failed (wrong proxy type?)"
}

function Invoke-Telegram([string]$proxyUrl, [string]$path) {
    # The URL (which may contain the token) goes to curl via stdin (-K -),
    # never on the command line; written raw so no BOM is prepended.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $curl
    $psi.Arguments = "-sS -K - --proxy `"$proxyUrl`" --max-time $TimeoutSeconds -w `"\n%{http_code}`""
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    # stdin's writer takes Console.InputEncoding; a BOM-free one keeps curl happy
    $savedEncoding = [Console]::InputEncoding
    try {
        [Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
        $p = [System.Diagnostics.Process]::Start($psi)
    } finally {
        [Console]::InputEncoding = $savedEncoding
    }
    $p.StandardInput.Write("url = `"https://api.telegram.org$path`"`n")
    $p.StandardInput.Close()
    $text = $p.StandardOutput.ReadToEnd()
    [void]$p.StandardError.ReadToEnd()
    $p.WaitForExit()
    $code = $p.ExitCode
    $status = ""
    if ($text -match "(\d{3})\s*$") { $status = $Matches[1]; $text = $text.Substring(0, $text.Length - 3).Trim() }
    return @{ exit = $code; status = $status; body = $text }
}

function Test-Proxy([string]$proxyUrl) {
    # curl's socks5h:// lets the proxy resolve api.telegram.org (avoids local DNS blocks)
    $curlProxy = $proxyUrl -replace '^socks5://', 'socks5h://'
    $r = Invoke-Telegram $curlProxy "/"
    if ($r.exit -eq 0 -and $r.status) { return @{ ok = $true; detail = "HTTP $($r.status)" } }
    $why = $CurlErrors[[int]$r.exit]; if (-not $why) { $why = "curl error $($r.exit)" }
    return @{ ok = $false; detail = $why }
}

Write-Host "Telegram proxy test"
Write-Host ""

# ---- 1) choose / detect the proxy -------------------------------------------
$configured = Read-EnvValue "TELEGRAM_PROXY"
if (-not $configured) { $configured = Read-EnvValue "PROXY_URL" }
$candidates = @()
if ($Proxy) { $candidates = @($Proxy) }
elseif ($configured -and -not $Detect) { $candidates = @($configured) }
else { $candidates = @("socks5://$HostPort", "http://$HostPort") }

$working = $null
foreach ($candidate in $candidates) {
    $result = Test-Proxy $candidate
    if ($result.ok) {
        Write-Host ("  [OK]   {0,-28} Telegram reachable ({1})" -f $candidate, $result.detail) -ForegroundColor Green
        if (-not $working) { $working = $candidate }
        break
    }
    Write-Host ("  [FAIL] {0,-28} {1}" -f $candidate, $result.detail) -ForegroundColor Yellow
}

if (-not $working) {
    Write-Host ""
    Write-Host "[ERROR] Telegram is not reachable through the proxy." -ForegroundColor Red
    Write-Host "        Is the proxy app (v2rayN / xray) running? Tried: $($candidates -join ', ')"
    Write-Host "        Check the port: Test-NetConnection 127.0.0.1 -Port $($HostPort.Split(':')[1])"
    exit 2
}
Write-Host ""
Write-Host "Working proxy: $working"
if ($configured -and $configured -ne $working) {
    Write-Host "Note: .env has TELEGRAM_PROXY=$configured (different)." -ForegroundColor Yellow
}

if ($Save -and $working -ne $configured) {
    & (Join-Path $PSScriptRoot "set_telegram_token.ps1") -EnvFile $EnvFile -KeepToken -Proxy $working `
        -AdminChatIds (Read-EnvValue "ADMIN_CHAT_IDS")
}

# ---- 2) getMe with the token (never shown) ---------------------------------
$token = Read-EnvValue "TELEGRAM_TOKEN"
if (-not $token) {
    Write-Host ""
    Write-Host "TELEGRAM_TOKEN is not set yet - skipped getMe. Run set_telegram_token.ps1 first."
    exit 0
}
$r = Invoke-Telegram ($working -replace '^socks5://', 'socks5h://') "/bot$token/getMe"
$token = $null
Write-Host ""
if ($r.exit -ne 0) {
    $why = $CurlErrors[[int]$r.exit]; if (-not $why) { $why = "curl error $($r.exit)" }
    Write-Host "[ERROR] getMe failed: $why" -ForegroundColor Red
    exit 3
}
try { $json = $r.body | ConvertFrom-Json } catch { $json = $null }
if ($r.status -eq "200" -and $json -and $json.ok) {
    Write-Host "[OK] getMe: bot @$($json.result.username) (id $($json.result.id)) - token is valid." -ForegroundColor Green
    exit 0
}
if ($r.status -eq "401" -or $r.status -eq "404") {
    Write-Host "[ERROR] Telegram rejected the token (HTTP $($r.status)). Run set_telegram_token.ps1 again." -ForegroundColor Red
    exit 4
}
Write-Host "[ERROR] unexpected answer from Telegram (HTTP $($r.status))." -ForegroundColor Red
exit 5
