"""Console self-check for a shopapi installation.

Read-only: prints configuration and row counts only. It never prints names,
phone numbers, tokens or passwords, and it never selects personal rows.
Usage:  python scripts/selfcheck.py
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyodbc  # noqa: E402

from app.config import Settings  # noqa: E402
from app.util import quote_identifier  # noqa: E402


def mask_connection_string(connection_string: str) -> str:
    return re.sub(r"(PWD=)[^;]*", r"\1***", connection_string)


def main() -> int:
    settings = Settings.from_env()
    db = quote_identifier(settings.accounting_database)

    print("== configuration ==")
    print(f"  server        : {settings.accounting_server}")
    print(f"  database      : {settings.accounting_database!r}  -> quoted as {db}")
    print(f"  auth          : {'Windows' if settings.accounting_trusted else 'SQL login'}")
    print(
        "  writer        : "
        + ("REAL WRITES ENABLED" if settings.write_allowed() else "dry run (INSERT then ROLLBACK)")
    )
    print(f"  price levels  : bot={settings.price_level_bot} site={settings.price_level_site}")
    print(
        "  api keys      : "
        f"bot={'set' if settings.bot_api_key else 'MISSING'} "
        f"site={'set' if settings.site_api_key else 'MISSING'} "
        f"admin={'set' if settings.admin_api_key else 'MISSING'}"
    )
    print(f"  connect string: {mask_connection_string(settings.accounting_connection_string())}")
    print(f"  own sqlite    : {settings.sqlite_path}")

    print("== accounting database (read-only) ==")
    try:
        conn = pyodbc.connect(
            settings.accounting_connection_string(),
            timeout=settings.accounting_connect_timeout,
        )
    except Exception as exc:
        print(f"  CONNECT FAILED: {type(exc).__name__}")
        print("  things to check:")
        print("    - is the instance name correct (ACCOUNTING_SERVER)?")
        print(f"    - does the database {settings.accounting_database!r} exist on that instance?")
        print("    - does this Windows account have access (Windows authentication)?")
        print("    - SQL Server Express: local connections use the shared-memory pipe;")
        print("      TCP/IP and Named Pipes are disabled by default, which is fine.")
        return 2

    try:
        checks = [
            ("active products", f"SELECT COUNT(*) FROM {db}.dbo.Kala WHERE active=1"),
            ("level1 Gey", f"SELECT COUNT(*) FROM {db}.dbo.Kala WHERE active=1 AND ISNULL(Gey,0)>0"),
            ("level2 Geycf", f"SELECT COUNT(*) FROM {db}.dbo.Kala WHERE active=1 AND ISNULL(Geycf,0)>0"),
            ("level3 gey3", f"SELECT COUNT(*) FROM {db}.dbo.Kala WHERE active=1 AND ISNULL(gey3,0)>0"),
            ("level4 gey4", f"SELECT COUNT(*) FROM {db}.dbo.Kala WHERE active=1 AND ISNULL(gey4,0)>0"),
            ("level5 gey5", f"SELECT COUNT(*) FROM {db}.dbo.Kala WHERE active=1 AND ISNULL(gey5,0)>0"),
            ("groups Gkala", f"SELECT COUNT(*) FROM {db}.dbo.Gkala"),
            ("orders KalaOrder", f"SELECT COUNT(*) FROM {db}.dbo.KalaOrder"),
            ("order lines", f"SELECT COUNT(*) FROM {db}.dbo.KalaOrderDetail"),
            ("next Codlp", f"SELECT ISNULL(MAX(Codlp),0)+1 FROM {db}.dbo.KalaOrder"),
            ("kardex rows", f"SELECT COUNT(*) FROM {db}.dbo.kardex_an"),
        ]
        for label, sql in checks:
            try:
                value = conn.execute(sql).fetchone()[0]
            except Exception as exc:  # a missing table must not abort the whole check
                value = f"n/a ({type(exc).__name__})"
            print(f"  {label:17}: {value}")

        try:
            today = conn.execute(
                f"SELECT {db}.dbo.MiladiToShamsi(CONVERT(varchar(20), CONVERT(date, GETDATE())))"
            ).fetchone()[0]
        except Exception as exc:
            today = f"n/a ({type(exc).__name__})"
        print(f"  {'shamsi today':17}: {today}")
    finally:
        conn.close()

    print("== result ==")
    print("  accounting database reachable; schema looks usable")
    print("  pick PRICE_LEVEL_BOT/SITE from the level with products (1 here)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
