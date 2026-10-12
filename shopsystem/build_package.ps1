<#
.SYNOPSIS
    Build the server update/install package (zip) from dist\ShopSystem.
.DESCRIPTION
    Run build_exe.bat (or ..\build_all.bat) first. Contents:
      ShopSystem\            the PyInstaller build (no .env, *.db, *.log, tls)
      install.ps1, update.ps1, uninstall.ps1, restore.ps1, firewall_sql.ps1, common.ps1,
      README_FA.txt, VERSION.txt
    Output: <OutDir>\ShopServer_<version>_<yyyy-MM-dd>.zip  (+ SHA-256 printed)
    The version comes from shopadmin\installer\ShopAdmin.iss (MyAppVersion).
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\build_package.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\build_package.ps1 -OutDir E:\Outputs\ShopSystem
#>
[CmdletBinding()]
param([string]$OutDir = "")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$dist = Join-Path $root "dist\ShopSystem"
if (-not (Test-Path (Join-Path $dist "ShopSystem.exe"))) { throw "dist\ShopSystem\ShopSystem.exe not found - run build_exe.bat first." }

$iss = Join-Path $root "..\shopadmin\installer\ShopAdmin.iss"
$version = ""
foreach ($line in Get-Content $iss) {
    if ($line -match '^#define\s+MyAppVersion\s+"([^"]+)"') { $version = $Matches[1]; break }
}
if (-not $version) { throw "MyAppVersion not found in $iss" }
$date = Get-Date -Format "yyyy-MM-dd"
$name = "ShopServer_${version}_$date"

$stage = Join-Path $root "build\package\$name"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# Program: everything except local state (the developer .env next to the exe stays out).
$exclude = @(".env", "*.db", "*.db-journal", "*.db-wal", "*.log", "*.dpapi", "fingerprint.txt")
Copy-Item $dist (Join-Path $stage "ShopSystem") -Recurse
Get-ChildItem (Join-Path $stage "ShopSystem") -Recurse -File -Force |
    Where-Object { $n = $_.Name; ($exclude | Where-Object { $n -like $_ }) } |
    Remove-Item -Force
foreach ($dir in @("tls", "receipts", "pricelists", "backups", "shoptg")) {
    $p = Join-Path $stage "ShopSystem\$dir"
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}
foreach ($file in @("install.ps1", "update.ps1", "uninstall.ps1", "restore.ps1", "firewall_sql.ps1", "common.ps1")) {
    Copy-Item (Join-Path $root "deploy\$file") $stage
}
# README with a BOM so Notepad shows the Persian text correctly
$readme = Get-Content (Join-Path $root "deploy\README_FA.txt") -Raw -Encoding UTF8
[IO.File]::WriteAllText((Join-Path $stage "README_FA.txt"), $readme, (New-Object Text.UTF8Encoding($true)))
Set-Content -Path (Join-Path $stage "VERSION.txt") -Value $version -Encoding ASCII

# Safety net: nothing secret or local may be inside.
$bad = Get-ChildItem $stage -Recurse -File -Force |
    Where-Object { $_.Name -eq ".env" -or $_.Extension -in @(".db", ".log", ".dpapi", ".key") }
if ($bad) { throw ("refusing to package local state: " + (($bad | ForEach-Object { $_.FullName }) -join ", ")) }

if (-not $OutDir) { $OutDir = Join-Path $root "dist\package" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$zip = Join-Path $OutDir "$name.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash
Write-Host "package : $zip"
Write-Host "version : $version"
Write-Host "SHA-256 : $hash"
