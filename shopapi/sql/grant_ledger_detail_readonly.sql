/* ============================================================================
   v2.18.3 «تشریحی گردش»: READ-ONLY access for role shop_ledger_read to the
   invoice header/line columns of the previous fiscal-year databases.
   SQL Server 2008 R2 compatible.

   Run in SSMS as sa, once, on the shop's SQL Server:
     1. Databases: every one of hesab1..hesab4 is processed; the working
        database (the one chosen in «تنظیمات سرور» - it holds role shop_app)
        is skipped automatically. NEVER add the working database yourself.
     2. Change @Login only if the shop's SQL login is not shopbot.
     3. Execute. Each database prints OK with the checks, or the reason it
        was skipped.
   Running this script again is safe: the database user and the role are created
   only when missing, role membership is added only when missing, and GRANT /
   DENY are idempotent. It reads and changes no accounting data: it only adds a
   database user, a database role and column-level SELECT grants.

   What the role gets in each database, and nothing else:
     * SELECT on dbo.Fact   (Numfact, Codename, Date1, Sharh)   - invoice header
     * SELECT on dbo.Facto  (Numfact, Radif, Codekala, Meg, Gey, Mab) - invoice
           lines (quantity, unit price, line amount)
     * SELECT on dbo.Kala   (Code, Name)                        - item name of a
           line, needed by the «تفصیلی» view of the ledger
     * an explicit DENY of INSERT, UPDATE, DELETE, EXECUTE and ALTER on the
       whole dbo schema
   No INSERT / UPDATE / DELETE / EXECUTE grant is ever given.
   To take it back:  USE [hesab4]; DROP ROLE shop_ledger_read;
   ============================================================================ */
SET NOCOUNT ON;

DECLARE @Databases nvarchar(max) = N'hesab1,hesab2,hesab3,hesab4';
DECLARE @Login sysname = N'shopbot';

IF SUSER_ID(@Login) IS NULL
BEGIN
    RAISERROR(N'Login %s does not exist on this server; nothing was changed.', 16, 1, @Login);
    RETURN;
END;

DECLARE @Db sysname, @Rest nvarchar(max) = @Databases + N',', @Comma int, @Sql nvarchar(max);
WHILE LEN(@Rest) > 0
BEGIN
    SET @Comma = CHARINDEX(N',', @Rest);
    SET @Db = LTRIM(RTRIM(LEFT(@Rest, @Comma - 1)));
    SET @Rest = SUBSTRING(@Rest, @Comma + 1, LEN(@Rest));
    IF @Db = N'' CONTINUE;
    IF DB_ID(@Db) IS NULL
    BEGIN
        PRINT @Db + N': no such database, skipped.';
        CONTINUE;
    END;

    SET @Sql = N'USE ' + QUOTENAME(@Db) + N';
DECLARE @user sysname;
SELECT @user = name FROM sys.database_principals WHERE sid = SUSER_SID(@login);
IF DATABASE_PRINCIPAL_ID(N''shop_app'') IS NOT NULL
BEGIN
    PRINT DB_NAME() + N'': this is the shop''s working database (role shop_app), skipped.'';
    RETURN;
END;
IF EXISTS (SELECT 1 FROM sys.database_role_members m
           JOIN sys.database_principals r ON r.principal_id = m.role_principal_id
           JOIN sys.database_principals u ON u.principal_id = m.member_principal_id
           WHERE r.name IN (N''db_owner'', N''db_datawriter'', N''db_ddladmin'') AND u.name = @user)
BEGIN
    PRINT DB_NAME() + N'': the login is in a role that can write here, skipped. Remove it from that role first.'';
    RETURN;
END;
BEGIN TRY
    IF @user IS NULL
    BEGIN
        SET @user = @login;
        DECLARE @create nvarchar(600);
        SET @create = N''CREATE USER '' + QUOTENAME(@login) + N'' FOR LOGIN '' + QUOTENAME(@login);
        EXEC (@create);
    END;
    IF DATABASE_PRINCIPAL_ID(N''shop_ledger_read'') IS NULL
        EXEC (N''CREATE ROLE shop_ledger_read AUTHORIZATION dbo'');
    IF NOT EXISTS (SELECT 1 FROM sys.database_role_members m
                   JOIN sys.database_principals r ON r.principal_id = m.role_principal_id
                   JOIN sys.database_principals u ON u.principal_id = m.member_principal_id
                   WHERE r.name = N''shop_ledger_read'' AND u.name = @user)
        EXEC sp_addrolemember N''shop_ledger_read'', @user;
    GRANT SELECT ON dbo.Fact (Numfact, Codename, Date1, Sharh) TO shop_ledger_read;
    GRANT SELECT ON dbo.Facto (Numfact, Radif, Codekala, Meg, Gey, Mab) TO shop_ledger_read;
    GRANT SELECT ON dbo.Kala (Code, Name) TO shop_ledger_read;
    DENY INSERT, UPDATE, DELETE, EXECUTE, ALTER ON SCHEMA::dbo TO shop_ledger_read;
    PRINT DB_NAME() + N'': OK, read-only.'';
END TRY
BEGIN CATCH
    PRINT DB_NAME() + N'': FAILED: '' + ERROR_MESSAGE();
END CATCH;';
    EXEC sp_executesql @Sql, N'@login sysname', @login = @Login;
END;