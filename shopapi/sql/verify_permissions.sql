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

PRINT '-- column-level permissions (name_mo) --';
SELECT OBJECT_NAME(prm.major_id) AS obj,
       c.name AS column_name,
       prm.permission_name,
       prm.state_desc
FROM sys.database_permissions prm
JOIN sys.columns c ON c.object_id = prm.major_id AND c.column_id = prm.minor_id
JOIN sys.database_principals p ON p.principal_id = prm.grantee_principal_id
WHERE p.name = N'shopbot';
GO
