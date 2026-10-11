# Runs all three live checks against the local TEST db and saves the output
# (no personal data) to live_db_check.out.txt next to this script.
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $PSScriptRoot 'live_db_check.out.txt'
Push-Location $root
try {
    foreach ($m in 'kol', 'r5', 'person') {
        "=== $m ===" | Out-File $out -Append -Encoding utf8
        & .\.venv\Scripts\python.exe scripts\live_db_check.py $m 2>&1 | Out-File $out -Append -Encoding utf8
    }
} finally { Pop-Location }
Get-Content $out -Encoding utf8
