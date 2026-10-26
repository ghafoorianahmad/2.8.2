"""v2.9.3: «دادن دسترسی به این دیتابیس» in the server setup (ShopSystem.exe
``--grant-db``), with the setup's own (administrator) Windows sign-in.

Exactly what ``deploy/grant_shop_app.ps1 -Apply [-CreateLogin]`` does, for the
database and the SQL sign-in chosen in the setup:

* the shop's login: the SQL login (``ACCOUNTING_USERNAME``) or, with Windows
  sign-in, the service account ``NT SERVICE\\ShopServer``; it is created when
  missing (a SQL login with the saved password, as ``-CreateLogin``);
* the database user of that login, when missing;
* the role ``shop_app`` with its least-privilege grants and denials
  (``sql/grant_shop_app.sql``, embedded below - a test keeps the two equal),
  and the user as a member.

Names travel as parameters (QUOTENAME on the server) or are checked against a
strict pattern before they are placed into the script; the password is only a
query parameter and is never printed or logged. Nothing is ever deleted.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Callable

#: the Windows service account of ShopServer (Windows sign-in to SQL Server)
SERVICE_LOGIN = "NT SERVICE\\ShopServer"
#: same rules as grant_shop_app.ps1 (names go into the SQL text, bracket-quoted)
DATABASE_RE = re.compile(r"^[A-Za-z0-9_ ]{1,64}$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
#: the service's Windows logins: NT SERVICE\ShopServer or DOMAIN\COMPUTER$
WINDOWS_LOGIN_RE = re.compile(r"^(NT SERVICE\\ShopServer|[A-Za-z0-9_.-]{1,64}\\[A-Za-z0-9_.-]{1,63}\$)$")
#: CREATE LOGIN ... FROM WINDOWS: the account does not exist (service not registered)
UNKNOWN_WINDOWS_ACCOUNT = frozenset({15401})
#: the database errors after which «دادن دسترسی» is offered (no user / no grant)
ACCESS_ERRORS = frozenset({"4060", "916", "229", "230", "18456", "4064"})
#: SQL Server answered «you may not» to the setup's own Windows account
NO_ADMIN_ERRORS = frozenset({15247, 15151, 262, 297, 300})
#: the role script refuses a db_owner member (it already has every right)
DB_OWNER_MARK = "is db_owner"

GRANT_SQL = """/* ============================================================================
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
-- v2.6.0: fname/Name = the linked customer's name in ShopAdmin's order dialog and on the
-- customer's own statement PDF. Still NO mobile/address/balance columns.
GRANT SELECT ON dbo.name_mo (Code, Gcod, l_gey, codetaf, fname, Name) TO shop_app;
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
"""


class GrantError(Exception):
    """A step failed; ``message_fa`` is Persian and safe to show."""

    def __init__(self, message_fa: str, detail: str = "") -> None:
        super().__init__(message_fa)
        self.message_fa = message_fa
        self.detail = detail


def shop_login(settings) -> tuple[str, bool]:
    """(login name, Windows sign-in?) the shop connects with. v2.9.4: exactly the
    account the SERVICE signs in with (``NT SERVICE\\ShopServer`` on this computer,
    ``DOMAIN\\COMPUTER$`` for a SQL Server on another one), never the person
    running the setup."""
    from .db_setup import shop_login as service_aware

    return service_aware(settings)


def grant_batches(database: str, user: str) -> list[str]:
    """The batches of grant_shop_app.sql for this database and database user."""
    if not DATABASE_RE.match(database or ""):
        raise GrantError(f"نام پایگاه‌داده «{database}» پذیرفته نیست (فقط حرف لاتین، رقم، _ "
                         "و فاصله).")
    if not WINDOWS_LOGIN_RE.match(user or "") and not LOGIN_RE.match(user or ""):
        raise GrantError(f"نام کاربری SQL «{user}» پذیرفته نیست (فقط حرف لاتین، رقم و _).")
    text = GRANT_SQL.replace("$(DB_NAME)", database.replace("]", "]]")).replace(
        "$(SHOP_USER)", user)
    return [b for b in re.split(r"(?im)^\s*GO\s*$", text) if b.strip()]


def admin_connection_string(settings) -> str:
    """The shop's server and driver, signed in with the CURRENT Windows account
    (the setup runs as an administrator), on ``master``."""
    from .db_setup import admin_connection_string as admin

    return admin(settings)


def _numbers(exc: BaseException) -> list[int]:
    from .sql_errors import _native_numbers

    return _native_numbers(" ".join(str(a) for a in getattr(exc, "args", ()) or ()))


def _sql_error(exc: BaseException) -> GrantError:
    from .sql_errors import describe

    text = " ".join(str(a) for a in getattr(exc, "args", ()) or ())
    if any(n in UNKNOWN_WINDOWS_ACCOUNT for n in _numbers(exc)):
        return GrantError("حساب سرویس «NT SERVICE\\ShopServer» هنوز روی این رایانه ثبت نشده است؛ "
                          "دوباره «دادن دسترسی» را بزنید (سرویس پیش از آن ثبت می‌شود).", text[:300])
    if any(n in NO_ADMIN_ERRORS for n in _numbers(exc)):
        return GrantError("حساب ویندوز شما در SQL Server اجازهٔ ساخت کاربر و دادن دسترسی ندارد. "
                          "«تنظیمات سرور» را با حسابی اجرا کنید که در SQL Server «sysadmin» است "
                          "(معمولاً همان حسابی که SQL Server را نصب کرده)، یا از مسئول SQL "
                          "بخواهید grant_shop_app.ps1 را اجرا کند.", text[:300])
    return GrantError(describe(exc).message_fa, text[:300])


def grant_shop_app(settings, connect: Callable | None = None) -> dict:
    """Give the shop's login exactly the shop_app access to the chosen database.
    Returns ``{ok, database, login, windows, steps, note}``; raises GrantError."""
    database = settings.accounting_database.strip()
    login, windows = shop_login(settings)
    if not login:
        raise GrantError("نام کاربری SQL خالی است.")
    if login.lower() == "sa":
        raise GrantError("فروشگاه هرگز با sa کار نمی‌کند؛ یک کاربر جدا (مثل shopbot) بسازید.")
    batches = grant_batches(database, login)
    if connect is None:
        import pyodbc

        connect = pyodbc.connect
    steps: list[str] = []
    note = ""
    try:
        conn = connect(admin_connection_string(settings),
                       timeout=max(5, int(settings.accounting_connect_timeout)), autocommit=True)
    except Exception as exc:  # noqa: BLE001 - pyodbc.Error and friends
        raise _sql_error(exc) from None
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM sys.server_principals WHERE name = ?", login)
        if cur.fetchone() is None:
            if windows:
                cur.execute("DECLARE @sql nvarchar(max) = N'CREATE LOGIN ' + QUOTENAME(?) "
                            "+ N' FROM WINDOWS'; EXEC (@sql);", login)
            else:
                password = settings.accounting_password
                if not password:
                    raise GrantError(f"کاربر SQL «{login}» روی سرور وجود ندارد و گذرواژه‌ای "
                                     "برای ساختنش ذخیره نشده؛ گذرواژه را بنویسید و دوباره "
                                     "«ذخیره و آزمایش اتصال» را بزنید.")
                cur.execute(
                    "DECLARE @sql nvarchar(max) = N'CREATE LOGIN ' + QUOTENAME(?) "
                    "+ N' WITH PASSWORD = ' + QUOTENAME(?, '''') "
                    "+ N', CHECK_POLICY = ON, DEFAULT_DATABASE = ' + QUOTENAME(?); EXEC (@sql);",
                    login, password, database)
            steps.append("login_created")
        cur.execute(
            "DECLARE @sql nvarchar(max) = N'USE ' + QUOTENAME(?) + N'; "
            "IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = ' "
            "+ QUOTENAME(?, '''') + N') CREATE USER ' + QUOTENAME(?) + N' FOR LOGIN ' "
            "+ QUOTENAME(?) + N';'; EXEC (@sql);", database, login, login, login)
        steps.append("user_ready")
        for index, batch in enumerate(batches):
            try:
                cur.execute(batch)
                while cur.nextset():
                    pass
            except Exception as exc:  # noqa: BLE001
                text = " ".join(str(a) for a in getattr(exc, "args", ()) or ())
                if index == len(batches) - 1 and DB_OWNER_MARK in text:
                    # the login is db_owner there: it already has every right
                    note = "db_owner"
                    continue
                raise
        steps.append("role_granted")
    except GrantError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _sql_error(exc) from None
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "database": database, "login": login, "windows": windows,
            "steps": steps, "note": note}
