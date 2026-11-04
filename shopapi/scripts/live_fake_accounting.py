"""v2.18.1: the real shopapi over real HTTP on 127.0.0.1, with a fake accounting database and throwaway
keys (nothing real is read or written), for ``shopbots/scripts/live_bot_check.py``.

    python scripts/live_fake_accounting.py 18765
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from app import deps  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db_own import OwnDB  # noqa: E402
from app.main import create_app  # noqa: E402
from app.staff import hash_token  # noqa: E402
from tests.conftest import TEST_GROUPS, FakeReader, FakeWriter, seed_products  # noqa: E402

BOSS_TOKEN = "live-check-boss"


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18765
    settings = Settings(
        accounting_driver="ODBC Driver 17 for SQL Server", accounting_server=r".\SQLEXPRESS",
        accounting_database="hesab5", bot_api_key="bot-key", site_api_key="site-key",
        admin_api_key="admin-key", sqlite_path=":memory:", sales_windows_enabled=False,
        accounting_status_code=6808, phone_stock_required=False, pending_max_order_items=5)
    db = OwnDB(":memory:")
    db.set_group_settings(TEST_GROUPS, "test")
    reader, writer = FakeReader(), FakeWriter()
    seed_products(reader)
    boss = db.create_staff("boss", "مدیر آزمایشی", "super_admin", "x")
    expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(timespec="seconds")
    db.create_session(hash_token(BOSS_TOKEN), boss["id"], expires)
    app = create_app()
    app.dependency_overrides[deps.get_settings] = lambda: settings
    app.dependency_overrides[deps.get_db] = lambda: db
    app.dependency_overrides[deps.get_reader] = lambda: reader
    app.dependency_overrides[deps.get_writer] = lambda: writer
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
