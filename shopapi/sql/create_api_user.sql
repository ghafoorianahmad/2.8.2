/* =====================================================================
   Least-privilege production login for the shopapi service account.
   SQL Server 2008 R2 compatible. Replace the placeholder password before
   running. Run as a sysadmin (server login) and dbo (database objects).

   WARNING: the dev copy's TabaghehBandi table was observed to contain
   free-text notes including personal/financial data. The SELECT grant below
   follows the spec, but production DBAs should re-check whether shopbot
   actually needs it before granting.
   ===================================================================== */

-- 1. Server login ------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'shopbot')
BEGIN
    CREATE LOGIN shopbot WITH PASSWORD = N'<<SET_STRONG_PASSWORD>>',
        CHECK_POLICY = ON;
END;
GO

-- 2. Database user (run in the target database context) -----------------
-- The dev copy is named "hesab5 t" (with a space), hence the brackets.
-- Change this to the real database name of the fiscal year.
USE [hesab5 t];
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'shopbot')
BEGIN
    CREATE USER shopbot FOR LOGIN shopbot;
END;
GO

-- 3. Read grants --------------------------------------------------------
GRANT SELECT ON dbo.Kala TO shopbot;
GRANT SELECT ON dbo.Gkala TO shopbot;
GRANT SELECT ON dbo.kardex_an TO shopbot;
GRANT SELECT ON dbo.KalaOrder TO shopbot;
GRANT SELECT ON dbo.KalaOrderDetail TO shopbot;
GRANT SELECT ON dbo.facto TO shopbot;
GRANT SELECT ON dbo.TabaghehBandi TO shopbot;
GRANT SELECT ON dbo.setting TO shopbot;
GO

-- 4. Column-level SELECT on name_mo (never whole-table read) ------------
GRANT SELECT ON dbo.name_mo (Code, Name, fname, mobile) TO shopbot;
GO

-- 5. Write grants for order creation ------------------------------------
GRANT INSERT ON dbo.KalaOrder TO shopbot;
GRANT INSERT ON dbo.KalaOrderDetail TO shopbot;
GO

-- 6. The Shamsi date function used when inserting orders ----------------
GRANT EXECUTE ON dbo.MiladiToShamsi TO shopbot;
GO

-- 7. Least privilege: no UPDATE/DELETE on order tables ------------------
DENY UPDATE, DELETE ON dbo.KalaOrder TO shopbot;
DENY UPDATE, DELETE ON dbo.KalaOrderDetail TO shopbot;
GO
