/* =====================================================================
   Read-only verification of the shopbot permissions.
   SQL Server 2008 R2 compatible. Run in the target database context.
   ===================================================================== */
SET NOCOUNT ON;

PRINT '-- server login (sysadmin must be 0) --';
SELECT name, is_disabled, IS_SRVROLEMEMBER('sysadmin', name) AS is_sysadmin
FROM sys.server_principals WHERE name = N'shopbot';

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
UNION ALL SELECT 'SELECT name_mo.Name (1)',       HAS_PERMS_BY_NAME('dbo.name_mo', 'OBJECT', 'SELECT', 'Name', 'COLUMN')
UNION ALL SELECT 'SELECT name_mo.Codemelli (1)',  HAS_PERMS_BY_NAME('dbo.name_mo', 'OBJECT', 'SELECT', 'Codemelli', 'COLUMN')
UNION ALL SELECT 'SELECT name_mo.Addres (1)',     HAS_PERMS_BY_NAME('dbo.name_mo', 'OBJECT', 'SELECT', 'Addres', 'COLUMN')
UNION ALL SELECT 'SELECT name_mo.Addres2 (1)',    HAS_PERMS_BY_NAME('dbo.name_mo', 'OBJECT', 'SELECT', 'Addres2', 'COLUMN')
UNION ALL SELECT 'UPDATE name_mo.Addres2 (1)',    HAS_PERMS_BY_NAME('dbo.name_mo', 'OBJECT', 'UPDATE', 'Addres2', 'COLUMN')
UNION ALL SELECT 'UPDATE name_mo.Codemelli (1)',  HAS_PERMS_BY_NAME('dbo.name_mo', 'OBJECT', 'UPDATE', 'Codemelli', 'COLUMN')
UNION ALL SELECT 'UPDATE name_mo.Addres (0)',     HAS_PERMS_BY_NAME('dbo.name_mo', 'OBJECT', 'UPDATE', 'Addres', 'COLUMN')
UNION ALL SELECT 'SELECT KOL.Bed (1)',            HAS_PERMS_BY_NAME('dbo.KOL', 'OBJECT', 'SELECT', 'Bed', 'COLUMN')
UNION ALL SELECT 'SELECT KOL.Sharh (1)',          HAS_PERMS_BY_NAME('dbo.KOL', 'OBJECT', 'SELECT', 'Sharh', 'COLUMN')
UNION ALL SELECT 'SELECT KOL.Date1 (1)',          HAS_PERMS_BY_NAME('dbo.KOL', 'OBJECT', 'SELECT', 'Date1', 'COLUMN')
UNION ALL SELECT 'SELECT setting (0)',            HAS_PERMS_BY_NAME('dbo.setting', 'OBJECT', 'SELECT')
UNION ALL SELECT 'SELECT Telegram_Setting (0)',   HAS_PERMS_BY_NAME('dbo.Telegram_Setting', 'OBJECT', 'SELECT')
UNION ALL SELECT 'SELECT api_online_setting (0)', HAS_PERMS_BY_NAME('dbo.api_online_setting', 'OBJECT', 'SELECT')
UNION ALL SELECT 'SELECT TabaghehBandi (0)',      HAS_PERMS_BY_NAME('dbo.TabaghehBandi', 'OBJECT', 'SELECT')
UNION ALL SELECT 'INSERT KalaOrder (1)',          HAS_PERMS_BY_NAME('dbo.KalaOrder', 'OBJECT', 'INSERT')
UNION ALL SELECT 'UPDATE KalaOrder (0)',          HAS_PERMS_BY_NAME('dbo.KalaOrder', 'OBJECT', 'UPDATE')
UNION ALL SELECT 'DELETE KalaOrderDetail (0)',    HAS_PERMS_BY_NAME('dbo.KalaOrderDetail', 'OBJECT', 'DELETE')
UNION ALL SELECT 'INSERT Fact (0)',               HAS_PERMS_BY_NAME('dbo.Fact', 'OBJECT', 'INSERT')
UNION ALL SELECT 'UPDATE Kala (0)',               HAS_PERMS_BY_NAME('dbo.Kala', 'OBJECT', 'UPDATE')
-- Phase 5 (REQUIREMENTS §10): every DENY of create_api_user.sql has a probe
UNION ALL SELECT 'DELETE KalaOrder (0)',          HAS_PERMS_BY_NAME('dbo.KalaOrder', 'OBJECT', 'DELETE')
UNION ALL SELECT 'UPDATE KalaOrderDetail (0)',    HAS_PERMS_BY_NAME('dbo.KalaOrderDetail', 'OBJECT', 'UPDATE')
UNION ALL SELECT 'DELETE name_mo (0)',            HAS_PERMS_BY_NAME('dbo.name_mo', 'OBJECT', 'DELETE')
UNION ALL SELECT 'SELECT name_mo.mobile (0)',     HAS_PERMS_BY_NAME('dbo.name_mo', 'OBJECT', 'SELECT', 'mobile', 'COLUMN')
UNION ALL SELECT 'INSERT KOL (0)',                HAS_PERMS_BY_NAME('dbo.KOL', 'OBJECT', 'INSERT')
UNION ALL SELECT 'UPDATE KOL (0)',                HAS_PERMS_BY_NAME('dbo.KOL', 'OBJECT', 'UPDATE')
UNION ALL SELECT 'DELETE KOL (0)',                HAS_PERMS_BY_NAME('dbo.KOL', 'OBJECT', 'DELETE')
UNION ALL SELECT 'UPDATE setting (0)',            HAS_PERMS_BY_NAME('dbo.setting', 'OBJECT', 'UPDATE')
UNION ALL SELECT 'UPDATE Telegram_Setting (0)',   HAS_PERMS_BY_NAME('dbo.Telegram_Setting', 'OBJECT', 'UPDATE')
UNION ALL SELECT 'member of db_owner (0)',        IS_MEMBER('db_owner')
UNION ALL SELECT 'member of db_datareader (0)',   IS_MEMBER('db_datareader')
UNION ALL SELECT 'member of db_datawriter (0)',   IS_MEMBER('db_datawriter');
REVERT;
GO
