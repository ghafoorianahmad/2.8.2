<#
.SYNOPSIS
    Start the Bale bot.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Check
    powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -DryRun
    powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -LogLevel DEBUG
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$DryRun,
    [string]$LogLevel = "INFO"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "No virtual environment found. Run .\setup.ps1 first."
}
if (-not (Test-Path (Join-Path $root ".env"))) {
    Write-Warning "No .env file found. Copy .env.example to .env and set the tokens/keys."
}

if ($Check) {
    & $venvPython -m app.main --check
    exit $LASTEXITCODE
}

$appArgs = @("-m", "app.main", "--log-level", $LogLevel)
if ($DryRun) { $appArgs += "--dry-run" }

if ($DryRun) {
    Write-Host "shopbots dry run: adapters start, no network call is made." -ForegroundColor Green
} else {
    Write-Host "shopbots is starting (Bale)." -ForegroundColor Green
    Write-Host "  shopapi : see SHOPAPI_BASE_URL in .env"
    Write-Host "  logs    : platform, update id and event type only - never tokens, names or phones"
    Write-Host "  press Ctrl+C to stop"
}
Write-Host ""

& $venvPython @appArgs
