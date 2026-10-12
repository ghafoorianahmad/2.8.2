<#
.SYNOPSIS
    Build the shoptg server package (zip) for the shop server.

.DESCRIPTION
    Staging: shoptg\dist\shoptg  (git-ignored). Contents:
      app\, scripts\, install.ps1, login.ps1, check_pricelist.ps1, run.ps1,
      requirements.txt, .env.example, README.md, SERVER_GUIDE.md,
      vendor\pricelist\ (copy of shopapi's parser + pricing, for the standalone check),
      wheels\ (all dependencies for Python 3.12 64-bit -> offline install).
    Never included: .env, *.db, *.log, sessions, tests, .venv.
    Output: <OutDir>\shoptg_server_<version>_<yyyy-MM-dd>.zip (+ SHA-256 printed).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\build_package.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\build_package.ps1 -OutDir E:\Outputs\ShopTG -PipExtra "--use-deprecated=legacy-certs"
#>
[CmdletBinding()]
param(
    [string]$OutDir = "",
    [string]$PipExtra = ""
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "Run .\install.ps1 -Dev first (the venv Python builds the wheels)." }

$info = (& $venvPython -c "import sys,struct;print('%d.%d %d' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P')*8))").Trim()
if ($info -ne "3.12 64") { throw "The wheels must be built with Python 3.12 64-bit (venv has $info)." }

$version = (& $venvPython -c "import sys; sys.path.insert(0, r'$root'); import app; print(app.__version__)").Trim()
$date = Get-Date -Format "yyyy-MM-dd"
$stage = Join-Path $root "dist\shoptg"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

foreach ($dir in @("app", "scripts")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $stage $dir) | Out-Null
    Get-ChildItem (Join-Path $root $dir) -Filter *.py -File | Copy-Item -Destination (Join-Path $stage $dir)
}
foreach ($file in @("install.ps1", "login.ps1", "check_pricelist.ps1", "run.ps1", "requirements.txt",
                    ".env.example", "README.md", "SERVER_GUIDE.md")) {
    Copy-Item (Join-Path $root $file) -Destination $stage
}

$parserSrc = Join-Path $root "..\shopapi\app\pricelist"
$vendor = Join-Path $stage "vendor\pricelist"
New-Item -ItemType Directory -Force -Path $vendor | Out-Null
foreach ($file in @("parser.py", "pricing.py")) { Copy-Item (Join-Path $parserSrc $file) -Destination $vendor }

Write-Host "Building wheels for Python 3.12 x64 ..."
$wheels = Join-Path $stage "wheels"
$pipArgs = @("-m", "pip", "wheel", "--disable-pip-version-check", "-r", (Join-Path $root "requirements.txt"), "-w", $wheels)
if ($PipExtra) { $pipArgs += $PipExtra.Split(" ") }
& $venvPython @pipArgs | Out-Null
if ($LASTEXITCODE -ne 0) { throw "pip wheel failed ($LASTEXITCODE)." }

# Offline install must work from the wheels alone.
$probe = Join-Path $root "dist\_probe_venv"
if (Test-Path $probe) { Remove-Item -Recurse -Force $probe }
$basePython = (& $venvPython -c "import sys; print(sys._base_executable)").Trim()
& $basePython -m venv $probe
& (Join-Path $probe "Scripts\python.exe") -m pip install --disable-pip-version-check --no-index --find-links $wheels -r (Join-Path $root "requirements.txt") | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Offline install from the wheels failed." }
Remove-Item -Recurse -Force $probe

# Safety: nothing secret or local may be in the package.
$bad = Get-ChildItem $stage -Recurse -Force -File | Where-Object {
    $_.Name -eq ".env" -or $_.Extension -in @(".db", ".log", ".dpapi", ".session") -or $_.FullName -like "*__pycache__*"
}
if ($bad) { $bad | ForEach-Object { Write-Host "  $($_.FullName)" }; throw "Forbidden files in the staging folder." }

if (-not $OutDir) { $OutDir = Join-Path $root "dist" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$zip = Join-Path $OutDir ("shoptg_server_{0}_{1}.zip" -f $version, $date)
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path $stage -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash
$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
$count = (Get-ChildItem $wheels -File).Count
Write-Host ""
Write-Host "Package : $zip ($size MB, $count wheels)" -ForegroundColor Green
Write-Host "SHA-256 : $hash"
