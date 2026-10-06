"""Read-only check: compare kardex_an stock with Kala.Mogod for 20 random products.

Prints only counts and product codes (never names or personal data).
Usage: python scripts/check_stock.py
"""
from __future__ import annotations

import os
import random
import sys

import pyodbc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Settings  # noqa: E402
from app.util import quote_identifier  # noqa: E402


def main() -> None:
    settings = Settings.from_env()
    # "hesab5 t" contains a space, so it must be quoted as a bracketed identifier.
    db = quote_identifier(settings.accounting_database)

    conn = pyodbc.connect(settings.accounting_connection_string())
    try:
        codes = [r[0] for r in conn.execute(f"SELECT Code FROM {db}.dbo.Kala ORDER BY Code")]
    finally:
        conn.close()

    sample = random.sample(codes, min(20, len(codes)))

    conn = pyodbc.connect(settings.accounting_connection_string())
    try:
        mismatches = []
        for code in sample:
            stock = conn.execute(
                f"SELECT ISNULL(SUM(Megv),0)-ISNULL(SUM(Megs),0) "
                f"FROM {db}.dbo.kardex_an WHERE Codekala = ?",
                code,
            ).fetchone()[0]
            mogod = conn.execute(
                f"SELECT Mogod FROM {db}.dbo.Kala WHERE Code = ?", code
            ).fetchone()[0]
            if abs(float(stock or 0) - float(mogod or 0)) > 1e-6:
                mismatches.append((code, stock, mogod))
    finally:
        conn.close()

    print(f"checked={len(sample)} mismatches={len(mismatches)}")
    for code, stock, mogod in mismatches:
        print(f"mismatch code={code} kardex={stock} mogod={mogod}")


if __name__ == "__main__":
    main()
