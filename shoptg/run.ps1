<#
.SYNOPSIS
    Run the shoptg worker (needs shopapi with WORKER_API_KEY).
.EXAMPLE
    .\run.ps1 -Check      # settings / session / shopapi report (no values printed)
    .\run.ps1             # run until Ctrl+C
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [string]$LogLevel = "INFO"
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "Run .\install.ps1 first." }
if ($Check) {
    & $venvPython -m app.main --check
    exit $LASTEXITCODE
}
& $venvPython -m app.main --log-level $LogLevel
exit $LASTEXITCODE
