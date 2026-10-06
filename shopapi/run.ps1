<#
.SYNOPSIS
    Start the shopapi API on Windows.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Port 8100 -Reload
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$Address = "127.0.0.1",
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "No virtual environment found. Run .\setup.ps1 first."
}
if (-not (Test-Path (Join-Path $root ".env"))) {
    Write-Warning "No .env file found. Copy .env.example to .env and set the API keys."
}

$uvicornArgs = @("-m", "uvicorn", "app.main:app", "--host", $Address, "--port", "$Port")
if ($Reload) { $uvicornArgs += "--reload" }

Write-Host ""
Write-Host "shopapi is starting on http://${Address}:${Port}" -ForegroundColor Green
Write-Host "  health : http://${Address}:${Port}/health"
Write-Host "  docs   : http://${Address}:${Port}/docs"
Write-Host "  auth   : X-API-Key header (BOT_API_KEY / SITE_API_KEY / ADMIN_API_KEY)"
Write-Host "  press Ctrl+C to stop"
Write-Host ""

& $venvPython @uvicornArgs
