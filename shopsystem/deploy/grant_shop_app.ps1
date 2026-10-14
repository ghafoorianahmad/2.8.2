<#
.SYNOPSIS
    Create the least-privilege role "shop_app" in the accounting database and
    put the shop's SQL user into it (v2.5.0; SAZEH_DB_REFERENCE §8, REQUIREMENTS §10).
.DESCRIPTION
    Runs sql\grant_shop_app.sql (next to this script, or ..\..\shopapi\sql in
    the repository) against -Database on -Server, signed in with YOUR Windows
    account (it must be sysadmin or db_owner there). Without -Apply nothing is
    changed: the script only prints what it would run.

    -CreateLogin also creates the SQL login + database user -LoginName when they
    do not exist. The password is asked for (hidden) and sent to SQL Server as a
    query parameter - never on a command line, never written to disk or a log.

    The shop never uses "sa". After this, put the login name/password into the
    server .env (ACCOUNTING_USERNAME / ACCOUNTING_PASSWORD) with the server setup.

    UNTESTED: written in a Linux session (2026-10-14). Try it on the test copy
    first:  .\grant_shop_app.ps1 -Server .\SQLEXPRESS -Database "hesab5 t" -Apply
    Check the result with sql\verify_permissions.sql.
.EXAMPLE
    .\grant_shop_app.ps1 -Server .\SAZEHHESAB -Database hesab5 -LoginName shopbot
    .\grant_shop_app.ps1 -Server .\SAZEHHESAB -Database hesab5 -LoginName shopbot -CreateLogin -Apply
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [Parameter(Mandatory = $true)][string]$Database,
    [string]$LoginName = 'shopbot',
    [switch]$CreateLogin,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'

# Only plain names: they are placed into SQL text (bracket-quoted).
if ($Database -notmatch '^[A-Za-z0-9_ ]{1,64}$') { throw "Invalid database name: $Database" }
if ($LoginName -notmatch '^[A-Za-z0-9_]{1,64}$') { throw "Invalid login name: $LoginName" }
if ($LoginName -ieq 'sa') { throw "The shop never uses sa." }

$candidates = @(
    (Join-Path $PSScriptRoot 'sql\grant_shop_app.sql'),
    (Join-Path $PSScriptRoot '..\sql\grant_shop_app.sql'),
    (Join-Path $PSScriptRoot '..\..\shopapi\sql\grant_shop_app.sql')
)
$sqlFile = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $sqlFile) { throw "grant_shop_app.sql not found next to this script." }

$text = [IO.File]::ReadAllText($sqlFile, [Text.Encoding]::UTF8)
$text = $text.Replace('$(DB_NAME)', $Database.Replace(']', ']]')).Replace('$(SHOP_USER)', $LoginName)
$batches = [regex]::Split($text, '(?im)^\s*GO\s*$') | Where-Object { $_.Trim() -ne '' }

Write-Host "Server: $Server   Database: [$Database]   User: $LoginName"
Write-Host ("Script: {0} ({1} batches)" -f $sqlFile, $batches.Count)
if (-not $Apply) {
    Write-Host "Dry run: nothing changed. Add -Apply to run it." -ForegroundColor Yellow
    if ($CreateLogin) { Write-Host "Would create login/user $LoginName if missing." }
    return
}

$builder = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
$builder['Data Source'] = $Server
$builder['Initial Catalog'] = 'master'
$builder['Integrated Security'] = $true
$conn = New-Object System.Data.SqlClient.SqlConnection $builder.ConnectionString
$conn.Open()
try {
    if ($CreateLogin) {
        $secure = Read-Host "Password for SQL login $LoginName" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
            $cmd = $conn.CreateCommand()
            # Names/password travel as parameters; QUOTENAME builds the DDL on the server.
            $cmd.CommandText = @"
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = @login)
BEGIN
    DECLARE @sql nvarchar(max) = N'CREATE LOGIN ' + QUOTENAME(@login)
        + N' WITH PASSWORD = ' + QUOTENAME(@pwd, '''')
        + N', CHECK_POLICY = ON, DEFAULT_DATABASE = ' + QUOTENAME(@db);
    EXEC (@sql);
END
"@
            [void]$cmd.Parameters.AddWithValue('@login', $LoginName)
            [void]$cmd.Parameters.AddWithValue('@pwd', $plain)
            [void]$cmd.Parameters.AddWithValue('@db', $Database)
            [void]$cmd.ExecuteNonQuery()
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
            $plain = $null
        }
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = @"
DECLARE @sql nvarchar(max) = N'USE ' + QUOTENAME(@db) + N';
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = ' + QUOTENAME(@login, '''') + N')
    CREATE USER ' + QUOTENAME(@login) + N' FOR LOGIN ' + QUOTENAME(@login) + N';';
EXEC (@sql);
"@
        [void]$cmd.Parameters.AddWithValue('@login', $LoginName)
        [void]$cmd.Parameters.AddWithValue('@db', $Database)
        [void]$cmd.ExecuteNonQuery()
        Write-Host "Login/user $LoginName ready."
    }
    foreach ($batch in $batches) {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = $batch
        $cmd.CommandTimeout = 60
        [void]$cmd.ExecuteNonQuery()
    }
    Write-Host "Role shop_app granted; $LoginName is a member." -ForegroundColor Green
} finally {
    $conn.Close()
}
