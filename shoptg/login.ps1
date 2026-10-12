<#
.SYNOPSIS
    One-time Telegram login of the shop account (elevated PowerShell, on the server).
    Every answer is typed into a hidden prompt; the session is saved encrypted.
#>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "Run .\install.ps1 first." }
& $venvPython (Join-Path $root "scripts\login.py")
exit $LASTEXITCODE
