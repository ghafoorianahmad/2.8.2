"""Verify the standalone exe's local database (smoke test helper)."""
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".smoketest/shopadmin.db")
connection = sqlite3.connect(str(path))
tables = sorted(
    row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
)
print("tables:", tables)
print("admin_users:", connection.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0])
print("settings keys:", sorted(
    row[0] for row in connection.execute("SELECT key FROM settings")
))
print("wizard_completed:", connection.execute(
    "SELECT value FROM settings WHERE key='wizard_completed'"
).fetchone())
print("base_url:", connection.execute(
    "SELECT value FROM settings WHERE key='shopapi_base_url'"
).fetchone())
connection.close()
