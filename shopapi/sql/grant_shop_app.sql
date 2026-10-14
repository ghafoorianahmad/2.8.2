/* ============================================================================
   Least-privilege database ROLE  shop_app  for shopapi (v2.5.0).
   SQL Server 2008 R2 compatible (CREATE ROLE + sp_addrolemember; no
   ALTER ROLE ... ADD MEMBER, which needs 2012).

   Same permissions as sql/create_api_user.sql / SAZEH_DB_REFERENCE §8, but
   granted to a role, so the login can be replaced without re-granting:
     * column-level SELECT only (no cost prices Geyk/Geya/Geym, no names,
       phones, addresses or balances of persons; KOL only the statement columns);
     * INSERT only into KalaOrder/KalaOrderDetail (orders) and
       name_mo/taf/DetailTBL (+ UPDATE name_mo.codetaf/telephons) for new customers;
     * EXECUTE only dbo.MiladiToShamsi;
     * explicit DENY of every UPDATE/DELETE on orders, of DELETE on persons,
       of any write on KOL, and of every access to setting / Telegram_Setting /
       api_online_setting / TabaghehBandi (credentials, personal notes).
   Nothing is ever deleted by the shop; the role cannot delete either.

   NOT VERIFIED ON A REAL SERVER (written in a Linux session, 2026-10-14):
   run it first on the test copy [hesab5 t], then check with
   sql/verify_permissions.sql (user = the login below) before production.

   Variables (sqlcmd syntax; deploy/grant_shop_app.ps1 fills them in):
     $(DB_NAME)    the fiscal-year accounting database, e.g. hesab5 or "hesab5 t"
     $(SHOP_USER)  the existing database user of the shop's SQL login (e.g. shopbot);
                   create the login/user first (grant_shop_app.ps1 can do it).
   Run as a sysadmin / db_owner. Never use sa for the shop itself.
   ============================================================================ */
USE [$(DB_NAME)];
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'shop_app' AND type = 'R')
    CREATE ROLE shop_app AUTHORIZATION dbo;
GO
-- ---- READ (column-level where a table also holds secrets/cost/personal data) ----
GRANT SELECT ON dbo.Kala (Code, Name, Gcod, Gey, Geycf, gey3, gey4, gey5, pic, v1, active, Mogod, hadeaghalmogodi) TO shop_app;
GRANT SELECT ON dbo.Gkala (Code, Name, g_kala) TO shop_app;
GRANT SELECT ON dbo.vahed (Code, Name) TO shop_app;
GRANT SELECT ON dbo.ANBAR (Code, Name) TO shop_app;
GRANT SELECT ON dbo.kardex_an (Codekala, Megv, Megs, Codanbar) TO shop_app;
GRANT SELECT ON dbo.KalaOrder TO shop_app;
GRANT SELECT ON dbo.KalaOrderDetail TO shop_app;
GRANT SELECT ON dbo.facto (Numfact, Codekala, Meg, ordercode, orderdetailcode) TO shop_app;
GRANT SELECT ON dbo.name_mo (Code, Gcod, l_gey, codetaf) TO shop_app;
GRANT SELECT ON dbo.DetailTBL (IDMaster, TabaghehBandiID, Va, Comment) TO shop_app;
GRANT SELECT ON dbo.taf (Code, Cota, codgtaf) TO shop_app;
GRANT SELECT ON dbo.KOL (Noa, Codkol, Bed, Bes, Va, Cod_n, Num_kol, Date1, N_sanad, Sharh) TO shop_app;
-- ---- WRITE: orders (INSERT only) ----
GRANT INSERT ON dbo.KalaOrder TO shop_app;
GRANT INSERT ON dbo.KalaOrderDetail TO shop_app;
-- ---- WRITE: new customers approved in ShopAdmin (recipe §5.1) ----
GRANT INSERT ON dbo.name_mo TO shop_app;
GRANT UPDATE ON dbo.name_mo (codetaf, telephons) TO shop_app;
GRANT INSERT ON dbo.taf TO shop_app;
GRANT INSERT ON dbo.DetailTBL TO shop_app;
GRANT EXECUTE ON dbo.MiladiToShamsi TO shop_app;
-- ---- explicit denials ----
DENY UPDATE, DELETE ON dbo.KalaOrder TO shop_app;
DENY UPDATE, DELETE ON dbo.KalaOrderDetail TO shop_app;
DENY DELETE ON dbo.name_mo TO shop_app;
DENY UPDATE, DELETE ON dbo.taf TO shop_app;
DENY UPDATE, DELETE ON dbo.DetailTBL TO shop_app;
DENY INSERT, UPDATE, DELETE ON dbo.KOL TO shop_app;
DENY INSERT, UPDATE, DELETE ON dbo.facto TO shop_app;
DENY INSERT, UPDATE, DELETE ON dbo.kardex_an TO shop_app;
DENY INSERT, UPDATE, DELETE ON dbo.Kala TO shop_app;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.setting TO shop_app;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.Telegram_Setting TO shop_app;
DENY SELECT, INSERT, UPDATE, DELETE ON dbo.api_online_setting TO shop_app;
DENY SELECT ON dbo.TabaghehBandi TO shop_app;
GO
-- ---- the shop's user joins the role (it must not be dbo / db_owner) ----
IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$(SHOP_USER)' AND type IN ('S', 'U'))
BEGIN
    IF IS_ROLEMEMBER('db_owner', N'$(SHOP_USER)') = 1
        RAISERROR(N'$(SHOP_USER) is db_owner: remove it from db_owner first.', 16, 1);
    ELSE
        EXEC sp_addrolemember N'shop_app', N'$(SHOP_USER)';
END
ELSE
    RAISERROR(N'database user $(SHOP_USER) not found: create the login and user first.', 16, 1);
GO
