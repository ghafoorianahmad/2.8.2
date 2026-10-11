/* =====================================================================
   Read-only verification of the shopbot permissions.
   SQL Server 2008 R2 compatible. Run in the target database context.
   ===================================================================== */
SET NOCOUNT ON;

PRINT '-- server login --';
SELECT name, is_disabled FROM sys.server_principals WHERE name = N'shopbot';

PRINT '-- database user --';
SELECT name, type_desc FROM sys.database_principals WHERE name = N'shopbot';

PRINT '-- object-level permissions (tables + functions) --';
SELECT OBJECT_SCHEMA_NAME(prm.major_id) AS sch,
       OBJECT_NAME(prm.major_id) AS obj,
       prm.permission_name,
       prm.state_desc
FROM sys.database_permissions prm
JOIN sys.database_principals p ON p.principal_id = prm.grantee_principal_id
WHERE p.name = N'shopbot'
  AND prm.class = 1          -- OBJECT_OR_COLUMN
  AND prm.minor_id = 0       -- object level only
ORDER BY sch, obj, prm.permission_name;

PRINT '-- column-level permissions (all tables) --';
SELECT OBJECT_NAME(prm.major_id) AS obj,
       c.name AS column_name,
       prm.permission_name,
       prm.state_desc
FROM sys.database_permissions prm
JOIN sys.columns c ON c.object_id = prm.major_id AND c.column_id = prm.minor_id
JOIN sys.database_principals p ON p.principal_id = prm.grantee_principal_id
WHERE p.name = N'shopbot'
ORDER BY obj, column_name;

PRINT '-- effective permissions as shopbot (1 = allowed; expected in the comment) --';
EXECUTE AS USER = N'shopbot';
SELECT 'SELECT Kala.Name (1)'           AS probe, HAS_PERMS_BY_NAME('dbo.Kala', 'OBJECT', 'SELECT', 'Name', 'COLUMN') AS allowed
UNION ALL SELECT 'SELECT Kala.Geyk (0)',          HAS_PERMS_BY_NAME('dbo.Kala', 'OBJECT', 'SELECT', 'Geyk', 'COLUMN')
UNION ALL SELECT 'SELECT DetailTBL.Comment (1)',  HAS_PERMS_BY_NAME('dbo.DetailTBL', 'OBJECT', 'SELECT', 'Comment', 'COLUMN')
UNION ALL SELECT 'SELECT name_mo.Name (0)',       HAS_PERMS_BY_NAME('dbo.name_mo', 'OBJECT', 'SELECT', 'Name', 'COLUMN')
UNION ALL SELECT 'SELECT KOL.Bed (1)',            HAS_PERMS_BY_NAME('dbo.KOL', 'OBJECT', 'SELECT', 'Bed', 'COLUMN')
UNION ALL SELECT 'SELECT setting (0)',            HAS_PERMS_BY_NAME('dbo.setting', 'OBJECT', 'SELECT')
UNION ALL SELECT 'SELECT Telegram_Setting (0)',   HAS_PERMS_BY_NAME('dbo.Telegram_Setting', 'OBJECT', 'SELECT')
UNION ALL SELECT 'SELECT api_online_setting (0)', HAS_PERMS_BY_NAME('dbo.api_online_setting', 'OBJECT', 'SELECT')
UNION ALL SELECT 'SELECT TabaghehBandi (0)',      HAS_PERMS_BY_NAME('dbo.TabaghehBandi', 'OBJECT', 'SELECT')
UNION ALL SELECT 'INSERT KalaOrder (1)',          HAS_PERMS_BY_NAME('dbo.KalaOrder', 'OBJECT', 'INSERT')
UNION ALL SELECT 'UPDATE KalaOrder (0)',          HAS_PERMS_BY_NAME('dbo.KalaOrder', 'OBJECT', 'UPDATE')
UNION ALL SELECT 'DELETE KalaOrderDetail (0)',    HAS_PERMS_BY_NAME('dbo.KalaOrderDetail', 'OBJECT', 'DELETE')
UNION ALL SELECT 'INSERT Fact (0)',               HAS_PERMS_BY_NAME('dbo.Fact', 'OBJECT', 'INSERT')
UNION ALL SELECT 'UPDATE Kala (0)',               HAS_PERMS_BY_NAME('dbo.Kala', 'OBJECT', 'UPDATE');
REVERT;
GO
