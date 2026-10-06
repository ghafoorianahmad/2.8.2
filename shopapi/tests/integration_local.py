"""Manual integration test against .\\SQLEXPRESS hesab5 (read-only copy).

Not collected by pytest (name does not match test_*.py). Run manually:
    python tests/integration_local.py
Prints only counts and the generated Codlp, never personal data.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.accounting_reader import AccountingReader  # noqa: E402
from app.accounting_writer import AccountingWriter  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db_own import OwnDB  # noqa: E402


def main() -> None:
    settings = Settings.from_env()
    reader = AccountingReader(settings)
    writer = AccountingWriter(settings)
    db = OwnDB(settings.sqlite_path)

    groups = reader.list_groups()
    print(f"groups={len(groups)}")

    page = reader.list_products(
        page=1,
        page_size=5,
        level=settings.price_level_bot,
        our_reservations=db.pending_reservations(),
    )
    print(f"products_page_count={len(page['items'])} total={page['total']}")
    for p in page["items"]:
        print(f"product code={p['code']} available_qty={p['available_qty']}")

    if page["items"]:
        first = page["items"][0]
        detail = reader.get_products_for_order(
            [first["code"]], settings.price_level_bot, db.pending_reservations()
        )
        print(f"availability_ok={first['code'] in detail}")

    # Dry-run write (dummy person/product codes; it must roll back).
    result = writer.write_order(999999, 1, [(1, 1.0, 1.0)])
    print(
        f"dryrun_codlp={result.accounting_order_no} "
        f"rolled_back={result.rolled_back} committed={result.committed} "
        f"idempotent={result.idempotent}"
    )

    print("integration_local done")


if __name__ == "__main__":
    main()
