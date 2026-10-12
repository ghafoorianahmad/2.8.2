<#
.SYNOPSIS
    Install shoptg (Telegram price/proxy worker): venv + dependencies + .env.

.DESCRIPTION
    Server (default): run from an ELEVATED PowerShell inside the shoptg folder.
      - creates .venv with Python 3.10+ (64-bit),
      - installs the pinned dependencies, offline from .\wheels when the
        package has them (built for Python 3.12 x64), otherwise from PyPI,
      - creates .env from .env.example (if missing) and limits it to
        SYSTEM + Administrators,
      - creates the data folder (%ProgramData%\ShopServer\shoptg) with the
        same restricted ACL.
    Nothing secret is asked for or printed: you type TG_API_ID / TG_API_HASH
    into .env yourself.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -PythonExe "C:\Program Files\Python312\python.exe"
.EXAMPLE
    # development PC: also pytest, no ACL changes, no admin needed
    powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Dev
#>
[CmdletBinding()]
param(
    [string]$PythonExe = "",
    [string]$IndexUrl = "",
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-Python {
    param([string]$Explicit)
    if ($Explicit) {
        if (-not (Test-Path $Explicit)) { throw "Python not found at: $Explicit" }
        return @($Explicit)
    }
    $py = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3.12 -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { return @($py.Source, "-3.12") }
        return @($py.Source, "-3")
    }
    foreach ($name in @("python.exe", "python3.exe")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notlike "*WindowsApps*") { return @($cmd.Source) }
    }
    throw "No Python found. Install Python 3.12 (64-bit) from python.org (tick 'Add python.exe to PATH') or pass -PythonExe."
}

if (-not $Dev -and -not (Test-Admin)) {
    throw "Run this from an elevated PowerShell (right-click PowerShell > Run as administrator)."
}

$python = Resolve-Python -Explicit $PythonExe
$pyExe = $python[0]
$pyArgs = @()
if ($python.Count -gt 1) { $pyArgs = $python[1..($python.Count - 1)] }

$info = & $pyExe @pyArgs -c "import sys,struct;print('%d.%d %d' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P')*8))"
if ($LASTEXITCODE -ne 0) { throw "Python did not start: $pyExe" }
$parts = $info.Trim().Split(" ")
$ver = [version]$parts[0]
Write-Host "Python   : $pyExe $($pyArgs -join ' ') ($($parts[0]), $($parts[1])-bit)"
if ($ver -lt [version]"3.10") { throw "Python 3.10 or newer is required." }
if ($parts[1] -ne "64") { throw "Install the 64-bit Python." }

$venvDir = Join-Path $root ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment (.venv) ..."
    & $pyExe @pyArgs -m venv $venvDir
    if (-not (Test-Path $venvPython)) { throw "Failed to create the virtual environment." }
} else {
    Write-Host "Virtual environment already present."
}

$req = Join-Path $root "requirements.txt"
if ($Dev) { $req = Join-Path $root "requirements-dev.txt" }
$wheels = Join-Path $root "wheels"
$pipArgs = @("-m", "pip", "install", "--disable-pip-version-check", "-r", $req)
$offline = (Test-Path $wheels) -and ($parts[0] -eq "3.12") -and -not $Dev
if ($offline) {
    Write-Host "Installing dependencies from the bundled wheels (offline) ..."
    $pipArgs += @("--no-index", "--find-links", $wheels)
} else {
    if (Test-Path $wheels) { Write-Host "Bundled wheels are for Python 3.12; installing from PyPI instead." }
    Write-Host "Installing dependencies from PyPI ..."
    if ($IndexUrl) { $pipArgs += @("-i", $IndexUrl) }
}
& $venvPython @pipArgs | Out-Host
if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE." }

& $venvPython -c "import telethon, httpx, dotenv, pdfplumber; print('Dependencies OK: Telethon', telethon.__version__)"
if ($LASTEXITCODE -ne 0) { throw "The dependencies did not import." }

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Write-Host "Created .env from .env.example." -ForegroundColor Yellow
} else {
    Write-Host ".env already present (left untouched)."
}

if (-not $Dev) {
    # .env holds TG_API_HASH and WORKER_API_KEY: SYSTEM + Administrators only.
    & icacls $envFile /inheritance:r /grant:r "*S-1-5-18:(F)" "*S-1-5-32-544:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls failed on .env" }
    $dataRoot = $env:ProgramData
    if (-not $dataRoot) { $dataRoot = "C:\ProgramData" }
    $dataDir = Join-Path $dataRoot "ShopServer\shoptg"
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    & icacls $dataDir /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)(F)" "*S-1-5-32-544:(OI)(CI)(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls failed on $dataDir" }
    Write-Host ".env and $dataDir are limited to SYSTEM and Administrators."
}

Write-Host ""
Write-Host "Install complete." -ForegroundColor Green
Write-Host "Next (same elevated PowerShell, in this folder):"
Write-Host "  notepad .env                 # type TG_API_ID, TG_API_HASH (and TG_PROXY) yourself, save"
Write-Host "  .\login.ps1                  # one-time Telegram login (hidden prompts)"
Write-Host "  .\check_pricelist.ps1        # read-only test: newest price PDF -> parsed"
