<#
.SYNOPSIS
    Read-only test: fetch the newest PDF of the price channel and parse it.
    Works without shopapi. Nothing is posted, joined or marked as read.
.EXAMPLE
    .\check_pricelist.ps1
    .\check_pricelist.ps1 -Save            # keep a copy of the PDF in the data folder
    .\check_pricelist.ps1 -Scan 200        # look further back
    .\check_pricelist.ps1 -ProxyChannels   # also count proxy links in TG_PROXY_CHANNELS
#>
[CmdletBinding()]
param(
    [switch]$Save,
    [int]$Scan = 50,
    [switch]$ProxyChannels
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "Run .\install.ps1 first." }
$a = @((Join-Path $root "scripts\check_pricelist.py"), "--scan", $Scan)
if ($Save) { $a += "--save" }
if ($ProxyChannels) { $a += "--proxy-channels" }
& $venvPython @a
exit $LASTEXITCODE
