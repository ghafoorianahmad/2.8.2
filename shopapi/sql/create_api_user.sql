/* ============================================================================
   Least-privilege SQL login for shopapi (SQL Server 2008 R2 compatible).
   Source: research_tools/recipes/grant_shopbot_2008r2.sql (SAZEH_DB_REFERENCE §8),
   VERIFIED on the local test copy: every read query (R1-R6) and both write
   recipes (person §5.1, order §5.2) pass; 13 negative probes are denied.
   + column-level SELECT on KOL for the customer statement (REQUIREMENTS §7, §10).

   DO NOT RUN ON PRODUCTION without the DBA reviewing it. Run as sysadmin.
   Replace the password and the database name (hesab1..hesab5 = fiscal year;
   the dev copy is [hesab5 t], with a space). Never use sa for the shop.
   Check the result with sql/verify_permissions.sql.
   ============================================================================ */
USE [master];
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'shopbot')
    CREATE LOGIN shopbot WITH PASSWORD = N'<<SET_STRONG_PASSWORD>>', CHECK_POLICY = ON, DEFAULT_DATABASE = [hesab5 t];
GO
USE [hesab5 t];   -- <<< the CURRENT fiscal-year database
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'shopbot')
    CREATE USER shopbot FOR LOGIN shopbot;
GO
-- ---- READ (column-level where a table also holds secrets/cost/personal data) ----
GRANT SELECT ON dbo.Kala (Code, Name, Gcod, Gey, Geycf, gey3, gey4, gey5, pic, v1, active, Mogod, hadeaghalmogodi) TO shopbot; -- NOT Geyk/Geya/Geym (cost / internal prices)
GRANT SELECT ON dbo.Gkala (Code, Name, g_kala) TO shopbot;
GRANT SELECT ON dbo.vahed (Code, Name) TO shopbot;
GRANT SELECT ON dbo.ANBAR (Code, Name) TO shopbot;
GRANT SELECT ON dbo.kardex_an (Codekala, Megv, Megs, Codanbar) TO shopbot;
GRANT SELECT ON dbo.KalaOrder TO shopbot;
GRANT SELECT ON dbo.KalaOrderDetail TO shopbot;
GRANT SELECT ON dbo.facto (Numfact, Codekala, Meg, ordercode, orderdetailcode) TO shopbot;
GRANT SELECT ON dbo.name_mo (Code, Gcod, l_gey, codetaf) TO shopbot;             -- NO names/phones/addresses/balances
GRANT SELECT ON dbo.DetailTBL (IDMaster, TabaghehBandiID, Va, Comment) TO shopbot; -- phone lookup R4 (mobiles live HERE, name_mo.mobile is empty)
GRANT SELECT ON dbo.taf (Code, Cota, codgtaf) TO shopbot;
-- Customer statement (balance formula, reference §3) + the paginated statement
-- rows (Phase 2): row id, date, document number and description.
GRANT SELECT ON dbo.KOL (Noa, Codkol, Bed, Bes, Va, Cod_n, Num_kol, Date1, N_sanad, Sharh) TO shopbot;
-- ---- WRITE: orders ----
GRANT INSERT ON dbo.KalaOrder TO shopbot;
GRANT INSERT ON dbo.KalaOrderDetail TO shopbot;
-- ---- WRITE: new customer (pending customers approved in shopadmin, §5.1) ----
GRANT INSERT ON dbo.name_mo TO shopbot;
GRANT UPDATE ON dbo.name_mo (codetaf, telephons) TO shopbot;
GRANT INSERT ON dbo.taf TO shopbot;
GRANT INSERT ON dbo.DetailTBL TO shopbot;
GRANT EXECUTE ON dbo.MiladiToShamsi TO shopbot;
-- ---- explicit denials (belt and braces; nothing else is granted) ----
DENY UPDATE, DELETE ON dbo.KalaOrder TO shopbot;
DENY UPDATE, DELETE ON dbo.KalaOrderDetail TO shopbot;
DENY DELETE ON dbo.name_mo TO shopbot;
DENY INSERT, UPDATE, DELETE ON dbo.KOL TO shopbot;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.setting TO shopbot;           -- SMS-panel and site API credentials
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.Telegram_Setting TO shopbot;  -- the vendor bot token
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.api_online_setting TO shopbot;
DENY SELECT ON dbo.TabaghehBandi TO shopbot;                              -- free-text notes with personal data
GO
