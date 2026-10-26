"""v2.9.4: the accounting connection in the server setup («تنظیمات سرور»), run by
ShopSystem.exe with the setup's own (administrator) Windows sign-in.

* :func:`list_databases` — every user database on the chosen SQL Server, for the
  database drop-down (no free typing: «hesab2» was typed by mistake in 2.9.3).
* :func:`diagnose` — the connection test with one precise answer:

  ``server_not_found``  SQL Server پیدا نشد (name / service / network)
  ``db_missing``        این پایگاه‌داده وجود ندارد
  ``no_access``         دسترسی نیست → «دادن دسترسی به این دیتابیس»
  ``bad_password``      the SQL login exists, its password is wrong
  ``remote_windows``    Windows sign-in to a SQL Server on another computer
                        outside a domain (the service account cannot reach it)
  ``error``             anything else (Persian text from :mod:`sql_errors`)

  With Windows sign-in the test runs **as the account the service connects
  with** (``NT SERVICE\\ShopServer``, or ``DOMAIN\\COMPUTER$`` for a SQL Server on
  another computer): the administrator connects and impersonates that login
  (``EXECUTE AS LOGIN``) for the same reads the server does. In 2.9.3 the test
  ran as the administrator, said «OK», and the service then failed to sign in.

Only SELECTs and ``EXECUTE AS`` / ``REVERT``; nothing is written. Names travel as
parameters (QUOTENAME on the server).
"""
from __future__ import annotations

import os
import re
import socket
from dataclasses import replace
from typing import Callable

from .sql_errors import _native_numbers, describe

SERVICE_NAME = "ShopServer"
SERVICE_LOGIN = "NT SERVICE\\" + SERVICE_NAME

#: native numbers / SQLSTATEs that mean «no SQL Server at that name»
SERVER_NOT_FOUND = frozenset({53, 2, -1, 17, 26, 87, 10060, 10061, 11001, 11004})
SERVER_NOT_FOUND_STATES = frozenset({"08001", "HYT00", "HYT01"})
#: the login works but may not open / read this database
NO_ACCESS = frozenset({4060, 916, 229, 230, 15517, 15401, 15404})
#: the administrator may not impersonate (not sysadmin)
NO_IMPERSONATE = frozenset({15406, 15157, 15199})

MESSAGES = {
    "server_not_found": (
        "SQL Server پیدا نشد",
        "نام سرور را بررسی کنید (روی همین رایانه معمولاً .\\SQLEXPRESS یا (local)). سرویس "
        "«SQL Server» (و برای نام نمونه «SQL Server Browser») باید روشن باشد؛ اگر SQL Server "
        "روی رایانهٔ دیگری است، TCP/IP آن روشن و دیوار آتش باز باشد."),
    "db_missing": (
        "این پایگاه‌داده وجود ندارد",
        "نام پایگاه‌داده را از فهرست کشویی انتخاب کنید (فهرست را با «خواندن فهرست» تازه کنید)."),
    "no_access": (
        "دسترسی نیست",
        "حسابی که سرور فروشگاه با آن وصل می‌شود به این پایگاه‌داده دسترسی ندارد. دکمهٔ «دادن "
        "دسترسی به این دیتابیس» را بزنید (حساب ویندوز شما باید در SQL Server «sysadmin» باشد)."),
    "bad_password": (
        "نام کاربری یا گذرواژهٔ SQL نادرست است",
        "گذرواژهٔ کاربر SQL را دوباره بنویسید؛ اگر آن را نمی‌دانید، مسئول SQL باید آن را عوض کند."),
    "remote_windows": (
        "احراز هویت ویندوز به SQL Server رایانهٔ دیگر نمی‌رسد",
        "این رایانه عضو دامنه نیست، پس حساب سرویس نمی‌تواند به SQL Server رایانهٔ دیگر وارد "
        "شود. «ورود SQL» را انتخاب کنید (کاربر محدود، مثل shopbot)."),
}


def is_local_server(server: str, names: set[str] | None = None) -> bool:
    """``.``, ``(local)``, ``localhost``, this computer's name or address, each with
    an optional ``\\INSTANCE`` / ``,port``."""
    host = re.split(r"[\\,]", str(server or "").strip(), maxsplit=1)[0].strip().lower()
    if host.startswith("tcp:") or host.startswith("np:") or host.startswith("lpc:"):
        host = host.split(":", 1)[1]
    if host in ("", ".", "(local)", "(localdb)", "localhost", "127.0.0.1", "::1"):
        return True
    if names is None:
        names = set()
        for value in (os.environ.get("COMPUTERNAME"), socket.gethostname()):
            if value:
                names.add(value.lower())
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                names.add(str(info[4][0]).lower())
        except OSError:
            pass
    return host in names


def in_domain() -> bool:
    domain = (os.environ.get("USERDOMAIN") or "").strip().lower()
    computer = (os.environ.get("COMPUTERNAME") or "").strip().lower()
    return bool(domain) and domain != computer


def service_sql_login(server: str, names: set[str] | None = None) -> str:
    """The Windows login SQL Server sees when the service connects: the virtual
    account on this computer, the computer account (``DOMAIN\\PC$``) on another."""
    if is_local_server(server, names):
        return SERVICE_LOGIN
    domain = os.environ.get("USERDOMAIN") or ""
    computer = os.environ.get("COMPUTERNAME") or socket.gethostname()
    return f"{domain}\\{computer}$"


def shop_login(settings) -> tuple[str, bool]:
    """(login, Windows sign-in?) the running shop server connects with."""
    if settings.accounting_trusted:
        return service_sql_login(settings.accounting_server), True
    return settings.accounting_username.strip(), False


def admin_connection_string(settings, database: str = "master") -> str:
    """The shop's server and driver, signed in with the CURRENT Windows account."""
    return replace(settings, accounting_trusted=True,
                   accounting_database=database).accounting_connection_string()


def _connect(connect: Callable | None):
    if connect is not None:
        return connect
    import pyodbc

    return pyodbc.connect


def _numbers(exc: BaseException) -> list[int]:
    return _native_numbers(" ".join(str(a) for a in getattr(exc, "args", ()) or ()))


def _state(exc: BaseException) -> str:
    args = getattr(exc, "args", ()) or ()
    return str(args[0]).strip().upper() if args and isinstance(args[0], str) else ""


def server_not_found(exc: BaseException) -> bool:
    numbers = set(_numbers(exc))
    if numbers & SERVER_NOT_FOUND:
        return True
    return not (numbers - {0}) and _state(exc) in SERVER_NOT_FOUND_STATES


def _close(conn) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def _answer(kind: str, *, code: str = "", **extra) -> dict:
    title, fix = MESSAGES.get(kind, ("", ""))
    return {"ok": False, "kind": kind, "error_code": code, "title_fa": title,
            "fix_fa": fix, "message_fa": f"{title}. {fix}".strip(". "), **extra}


def _error(exc: BaseException, **extra) -> dict:
    info = describe(exc)
    answer = {"ok": False, "kind": "error", "error_code": info.code, "title_fa": "اتصال برقرار نشد",
              "fix_fa": "", "message_fa": info.message_fa}
    answer.update(extra)
    return answer


# --------------------------------------------------------------------------
# database list
# --------------------------------------------------------------------------
LIST_SQL = ("SET NOCOUNT ON; SELECT name FROM sys.databases "
            "WHERE database_id > 4 AND state = 0 AND name NOT IN ('ReportServer', "
            "'ReportServerTempDB') ORDER BY name")


def list_databases(settings, connect: Callable | None = None) -> dict:
    """``{ok, databases}`` of the chosen server: first with this Windows account,
    then (when given) with the shop's SQL login. ``kind`` on failure."""
    connect = _connect(connect)
    attempts = [admin_connection_string(settings)]
    if not settings.accounting_trusted and settings.accounting_username.strip() \
            and settings.accounting_password:
        try:
            attempts.append(replace(settings, accounting_database="master")
                            .accounting_connection_string())
        except ValueError:      # sa is refused
            pass
    last: BaseException | None = None
    for text in attempts:
        try:
            conn = connect(text, timeout=max(5, int(settings.accounting_connect_timeout)))
        except Exception as exc:  # noqa: BLE001 - pyodbc.Error and friends
            if server_not_found(exc):
                return _answer("server_not_found", code=str((_numbers(exc) or [""])[0]))
            last = exc
            continue
        try:
            rows = conn.cursor().execute(LIST_SQL).fetchall()
            return {"ok": True, "databases": [str(r[0]) for r in rows]}
        except Exception as exc:  # noqa: BLE001
            last = exc
        finally:
            _close(conn)
    return _error(last) if last is not None else _answer("error")


# --------------------------------------------------------------------------
# the connection test
# --------------------------------------------------------------------------
#: the same tables the server reads first (column grants of the shop_app role)
#: run on ``master`` (the administrator needs no right in the shop's database):
#: the login and the database are parameters, quoted by the server
SERVICE_READ_SQL = ("SET NOCOUNT ON; DECLARE @sql nvarchar(max) = N'EXECUTE AS LOGIN = ' "
                    "+ QUOTENAME(?, '''') + N'; SELECT COUNT(*) FROM ' + QUOTENAME(?) "
                    "+ N'.dbo.Gkala WHERE Code > 0; REVERT;'; EXEC (@sql);")


def check_as_service(settings, connect: Callable | None = None) -> dict:
    """Windows sign-in: can the service's login read the chosen database?
    ``{ok, verified, login, groups}`` or a failure answer."""
    connect = _connect(connect)
    login = service_sql_login(settings.accounting_server)
    database = settings.accounting_database.strip()
    if not is_local_server(settings.accounting_server) and not in_domain():
        return _answer("remote_windows", login=login)
    try:
        conn = connect(admin_connection_string(settings),
                       timeout=max(5, int(settings.accounting_connect_timeout)), autocommit=True)
    except Exception as exc:  # noqa: BLE001
        if server_not_found(exc):
            return _answer("server_not_found", login=login)
        # this Windows account cannot sign in to SQL Server: nothing to compare with
        return {"ok": True, "verified": False, "login": login,
                "note_fa": "حساب ویندوز شما به SQL Server وارد نشد، پس آزمایش با حساب سرویس "
                           "ممکن نشد."}
    try:
        cur = conn.cursor()
        if cur.execute("SELECT 1 FROM sys.server_principals WHERE name = ?",
                       login).fetchone() is None:
            return _answer("no_access", login=login, verified=True, reason="no_login")
        try:
            row = cur.execute(SERVICE_READ_SQL, login, database).fetchone()
        except Exception as exc:  # noqa: BLE001
            numbers = set(_numbers(exc))
            if numbers & NO_IMPERSONATE:
                return {"ok": True, "verified": False, "login": login,
                        "note_fa": "حساب ویندوز شما در SQL Server «sysadmin» نیست، پس آزمایش با "
                                   "حساب سرویس ممکن نشد."}
            if numbers & NO_ACCESS or "4060" in str(exc):
                return _answer("no_access", code=str(min(numbers & NO_ACCESS or {4060})),
                               login=login, verified=True)
            return _error(exc, login=login, verified=True)
        return {"ok": True, "verified": True, "login": login,
                "groups": int(row[0]) if row else 0}
    finally:
        _close(conn)


def diagnose(settings, connect: Callable | None = None,
             reader_factory: Callable | None = None) -> dict:
    """The setup's «آزمایش اتصال»: ``{ok, groups, login, windows, as_service}`` or
    ``{ok: False, kind, title_fa, fix_fa, message_fa, error_code}``."""
    connect = _connect(connect)
    database = settings.accounting_database.strip()
    login, windows = shop_login(settings)
    base = {"login": login, "windows": windows, "database": database}

    # 1. the server, and whether the database exists (this administrator)
    admin_ok = False
    try:
        conn = connect(admin_connection_string(settings),
                       timeout=max(5, int(settings.accounting_connect_timeout)))
    except Exception as exc:  # noqa: BLE001
        if server_not_found(exc):
            return {**base, **_answer("server_not_found",
                                      code=str((_numbers(exc) or [""])[0]))}
        conn = None
    if conn is not None:
        try:
            cur = conn.cursor()
            row = cur.execute("SELECT DB_ID(?)", database).fetchone()
            admin_ok = True
            if row is None or row[0] is None:
                names = [str(r[0]) for r in cur.execute(LIST_SQL).fetchall()]
                return {**base, **_answer("db_missing", databases=names)}
            if not windows:
                exists = cur.execute("SELECT 1 FROM sys.server_principals WHERE name = ?",
                                     login).fetchone()
                base["sql_login_exists"] = exists is not None
        except Exception:  # noqa: BLE001 - the shop's own test below still runs
            pass
        finally:
            _close(conn)

    # 2. the shop's own connection (as the server does it)
    if reader_factory is None:
        from .accounting_reader import AccountingReader

        reader_factory = AccountingReader
    groups = 0
    try:
        reader = reader_factory(settings)
        reader.ping()
        groups = len(reader.list_groups())
    except Exception as exc:  # noqa: BLE001
        numbers = set(_numbers(exc))
        if windows and not server_not_found(exc) and (numbers & NO_ACCESS or 18456 in numbers):
            # this administrator may not read it; what counts is the service account
            service = check_as_service(settings, connect)
            if service.get("ok") and service.get("verified"):
                return {**base, "ok": True, "groups": service.get("groups", 0),
                        "as_service": True, "note_fa": ""}
            if not service.get("ok"):
                return {**base, **service}
        if server_not_found(exc):
            return {**base, **_answer("server_not_found", code=str((list(numbers) or [""])[0]))}
        if 18456 in numbers and not windows:
            if admin_ok and base.get("sql_login_exists") is False:
                return {**base, **_answer("no_access", code="18456", reason="no_login")}
            return {**base, **_answer("bad_password", code="18456")}
        if numbers & NO_ACCESS or 18456 in numbers:
            return {**base, **_answer("no_access", code=str(min(numbers & (NO_ACCESS | {18456}))))}
        return {**base, **_error(exc)}

    # 3. Windows sign-in: the same reads as the service account
    if windows:
        service = check_as_service(settings, connect)
        if not service.get("ok"):
            return {**base, **service}
        return {**base, "ok": True, "groups": groups, "as_service": service.get("verified"),
                "note_fa": service.get("note_fa", "")}
    return {**base, "ok": True, "groups": groups, "as_service": None}
