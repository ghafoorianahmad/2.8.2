/* ============================================================================
   Least-privilege SQL login for the shop system (SQL Server 2008 R2 compatible).
   VERIFIED on the local TEST copy (hesab5) with: CREATE USER ... WITHOUT LOGIN +
   EXECUTE AS USER, running every read query + both write recipes in
   research_tools/recipes (all passed) and 13 negative probes (all denied).

   DO NOT RUN ON PRODUCTION without the DBA reviewing it. Replace the password,
   the database name (hesab1..hesab5 = fiscal year) and keep the shop's own
   state (customers' chat ids, carts, bot tokens) in the shop's SQLite, not here.
   ============================================================================ */
USE [master];
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'shopbot')
    CREATE LOGIN shopbot WITH PASSWORD = N'<<SET_STRONG_PASSWORD>>', CHECK_POLICY = ON, DEFAULT_DATABASE = [hesab5];
GO
USE [hesab5];   -- <<< the CURRENT fiscal-year database
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
GRANT SELECT ON dbo.DetailTBL (IDMaster, TabaghehBandiID, Va, Comment) TO shopbot; -- phone lookup (mobiles live HERE, name_mo.mobile is empty)
GRANT SELECT ON dbo.taf (Code, Cota, codgtaf) TO shopbot;
-- ---- WRITE: orders ----
GRANT INSERT ON dbo.KalaOrder TO shopbot;
GRANT INSERT ON dbo.KalaOrderDetail TO shopbot;
-- ---- WRITE: new customer (only if the shop must create persons) ----
GRANT INSERT ON dbo.name_mo TO shopbot;
GRANT UPDATE ON dbo.name_mo (codetaf, telephons) TO shopbot;
GRANT INSERT ON dbo.taf TO shopbot;
GRANT INSERT ON dbo.DetailTBL TO shopbot;
GRANT EXECUTE ON dbo.MiladiToShamsi TO shopbot;
-- ---- explicit denials (belt and braces; nothing else is granted) ----
DENY UPDATE, DELETE ON dbo.KalaOrder TO shopbot;
DENY UPDATE, DELETE ON dbo.KalaOrderDetail TO shopbot;
DENY DELETE ON dbo.name_mo TO shopbot;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.setting TO shopbot;           -- holds SMS-panel credentials (rows 497-499) and site API credentials (648-650)
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.Telegram_Setting TO shopbot;  -- holds the vendor bot token
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.api_online_setting TO shopbot;
DENY SELECT ON dbo.TabaghehBandi TO shopbot;                              -- free-text notes with personal data
GO
