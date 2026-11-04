/* ============================================================================
   v2.18.2 «گردش سال‌های قبل»: READ-ONLY access for the shop's SQL login to the
   previous fiscal-year databases. SQL Server 2008 R2 compatible.

   Run in SSMS as sa, once, on the shop's SQL Server:
     1. Put the databases in @Databases below (comma separated, e.g. hesab4,hesab3).
        NEVER the working database chosen in «تنظیمات سرور»: it is skipped anyway.
     2. Change @Login only if the shop's login is not shopbot.
     3. Execute. Each database prints OK with the checks, or the reason it was skipped.
   Running it again is safe. It reads and changes no accounting data: it only adds
   a database user and a role with SELECT on these columns.

   What the login gets in each database, and nothing else:
     * SELECT on name_mo (Code, fname, Name, Codemelli),
       DetailTBL (IDMaster, TabaghehBandiID, Va, Comment) and the KOL statement columns;
     * an explicit DENY of INSERT, UPDATE, DELETE, EXECUTE and ALTER on the whole schema.
   To take it back:  USE [hesab4]; DROP USER [shopbot];
   ============================================================================ */
SET NOCOUNT ON;

DECLARE @Databases nvarchar(max) = N'hesab4,hesab3';
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
    PRINT DB_NAME() + N'': this is the shop''''s working database (role shop_app), skipped.'';
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
    GRANT SELECT ON dbo.name_mo (Code, fname, Name, Codemelli) TO shop_ledger_read;
    GRANT SELECT ON dbo.DetailTBL (IDMaster, TabaghehBandiID, Va, Comment) TO shop_ledger_read;
    GRANT SELECT ON dbo.KOL (Noa, Codkol, Bed, Bes, Va, Cod_n, Num_kol, Date1, N_sanad, Sharh) TO shop_ledger_read;
    DENY INSERT, UPDATE, DELETE, EXECUTE, ALTER ON SCHEMA::dbo TO shop_ledger_read;
    EXEC sp_addrolemember N''shop_ledger_read'', @user;
    PRINT DB_NAME() + N'': OK, read-only.'';
END TRY
BEGIN CATCH
    PRINT DB_NAME() + N'': FAILED: '' + ERROR_MESSAGE();
END CATCH;';
    EXEC sp_executesql @Sql, N'@login sysname', @login = @Login;
END;
