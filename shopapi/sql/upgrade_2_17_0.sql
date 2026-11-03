/* ============================================================================
   ShopSystem 2.17.0 — run ONCE in SSMS as sa, on the production database hesab5.
   Adds only what 2.17.0 needs to the role shop_app (the login shopbot is in it).
   SQL Server 2008 R2 compatible. Safe to run twice. Nothing else is changed:
     * no new table, column, index or trigger;
     * nothing is read or printed from any row;
     * no DELETE is allowed anywhere, and TabaghehBandi stays closed.

   Why: the bot asks a customer for what is missing and fills only EMPTY fields of
   the person in «سازه حساب» (first name, last name, national code, address).
   Without this script the shop still works, but those fields stay in the shop's own
   database and the bot does not see what «سازه حساب» already knows.
   ============================================================================ */
USE [hesab5];
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'shop_app' AND type = 'R')
    RAISERROR(N'role shop_app not found: run sql/grant_shop_app.sql first.', 16, 1);
GO
GRANT SELECT ON dbo.name_mo (fname, Name, Codemelli, Addres, Addres2) TO shop_app;
GRANT UPDATE ON dbo.name_mo (fname, Name, Codemelli, Addres2) TO shop_app;
GO
-- Check: the role's rights on name_mo (names of rights and columns only, no data).
SELECT p.state_desc, p.permission_name, c.name AS column_name
FROM sys.database_permissions p
JOIN sys.database_principals r ON r.principal_id = p.grantee_principal_id
LEFT JOIN sys.columns c ON c.object_id = p.major_id AND c.column_id = p.minor_id
WHERE r.name = N'shop_app' AND p.major_id = OBJECT_ID(N'dbo.name_mo')
ORDER BY p.permission_name, c.name;
GO
