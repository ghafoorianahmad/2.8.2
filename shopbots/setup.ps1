<#
.SYNOPSIS
    One-time setup for shopbots (Bale) on Windows.

.DESCRIPTION
    Creates .venv, installs requirements.txt and creates a local .env from
    .env.example when none exists yet.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1

.EXAMPLE
    # slow or filtered PyPI? use a mirror
    powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple/
#>
[CmdletBinding()]
param(
    [string]$PythonExe = "",
    [string]$IndexUrl = ""
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Resolve-Python {
    param([string]$Explicit)
    if ($Explicit) {
        if (-not (Test-Path $Explicit)) { throw "Python not found at: $Explicit" }
        return $Explicit
    }
    foreach ($name in @("py.exe", "python.exe", "python3.exe")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    throw "No Python interpreter found. Install Python 3.10+ or pass -PythonExe <path>."
}

$python = Resolve-Python -Explicit $PythonExe
Write-Host "Python   : $python"
Write-Host "Project  : $root"
Write-Host ""

$venvDir = Join-Path $root ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment (.venv) ..."
    if ([System.IO.Path]::GetFileName($python).ToLowerInvariant() -eq "py.exe") {
        & $python -3 -m venv $venvDir
    } else {
        & $python -m venv $venvDir
    }
    if (-not (Test-Path $venvPython)) { throw "Failed to create the virtual environment." }
} else {
    Write-Host "Virtual environment already present."
}

Write-Host "Installing dependencies ..."
& $venvPython -m pip install --upgrade pip | Out-Host

# shop-tgproxy (Telegram channel) is the repo's ..\shared package.
& $venvPython -m pip install (Join-Path $root "..\shared") | Out-Host
if ($LASTEXITCODE -ne 0) { throw "pip install ..\shared failed with exit code $LASTEXITCODE." }
$pipArgs = @("-m", "pip", "install", "-r", (Join-Path $root "requirements.txt"))
if ($IndexUrl) { $pipArgs += @("-i", $IndexUrl) }
& $venvPython @pipArgs | Out-Host
if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE." }

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Write-Host "Created .env from .env.example - fill in the tokens and keys." -ForegroundColor Yellow
} else {
    Write-Host ".env already present (left untouched)."
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  .\run.ps1 -Check      # show which platforms and how many admins are configured"
Write-Host "  .\run.ps1 -DryRun     # start both bots without touching the network"
Write-Host "  .\run.ps1             # run for real (needs BALE_TOKEN)"
