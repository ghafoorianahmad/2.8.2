<#
.SYNOPSIS
    Check a shopapi installation: accounting database, then the running API.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\check.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\check.ps1 -Port 8100
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$Address = "127.0.0.1"
)

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "No virtual environment found. Run .\setup.ps1 first."
}

Write-Host "=== 1/3  configuration + accounting database ===" -ForegroundColor Cyan
& $venvPython (Join-Path $root "scripts\selfcheck.py")
$dbExit = $LASTEXITCODE

Write-Host ""
Write-Host "=== 2/3  running API ===" -ForegroundColor Cyan
$base = "http://${Address}:${Port}"
$healthOk = $false
try {
    $health = Invoke-RestMethod "$base/health" -TimeoutSec 5
    Write-Host "  /health  -> $($health | ConvertTo-Json -Compress)" -ForegroundColor Green
    $healthOk = $true
} catch {
    Write-Host "  /health  -> not reachable. Start it with .\run.ps1" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== 3/3  authenticated endpoints (needs the keys from .env) ===" -ForegroundColor Cyan
if ($healthOk) {
    $envFile = Join-Path $root ".env"
    $botKey = ""
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*BOT_API_KEY\s*=\s*(.+?)\s*$') { $botKey = $Matches[1] }
        }
    }
    if (-not $botKey) {
        Write-Host "  BOT_API_KEY is not set in .env - skipping." -ForegroundColor Yellow
    } else {
        foreach ($endpoint in @("/groups", "/products?page_size=3")) {
            try {
                $response = Invoke-RestMethod "$base$endpoint" -Headers @{ "X-API-Key" = $botKey } -TimeoutSec 20
                if ($endpoint -like "/groups*") {
                    Write-Host "  $endpoint -> $($response.Count) groups" -ForegroundColor Green
                } else {
                    Write-Host "  $endpoint -> total=$($response.total) items=$($response.items.Count)" -ForegroundColor Green
                }
            } catch {
                $code = $_.Exception.Response.StatusCode.value__
                if ($code) {
                    Write-Host "  $endpoint -> HTTP $code" -ForegroundColor Yellow
                } else {
                    Write-Host "  $endpoint -> failed: $($_.Exception.Message)" -ForegroundColor Yellow
                }
            }
        }
    }
}

Write-Host ""
if ($dbExit -eq 0) {
    Write-Host "check finished: accounting database OK" -ForegroundColor Green
} else {
    Write-Host "check finished: accounting database NOT reachable (see above)" -ForegroundColor Red
}
exit $dbExit
