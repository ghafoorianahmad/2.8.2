"""v2.18.0: manual archive with its own tick; collected proxies that stay down are deleted."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.proxypool import ProxyLink, ProxyPool

from .conftest import h
from .test_v2170 import staff

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
SECRET = "dd" + "ab" * 16


def _order(db, status="written", **fields) -> int:
    user = db._conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    if user is None:
        db._conn.execute(
            "INSERT INTO users (platform, chat_id, name, phone, status, created_at) "
            "VALUES ('bale','1','x','09120000000','approved','2026-01-01')")
        user = db._conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    cur = db._conn.execute(
        "INSERT INTO orders (user_id, status, price_level, total, created_at, updated_at) "
        "VALUES (?,?,3,100,'2026-01-01','2026-01-01')", (user[0], status))
    for key, value in fields.items():
        db._conn.execute(f"UPDATE orders SET {key}=? WHERE id=?", (value, cur.lastrowid))
    db._conn.commit()
    return cur.lastrowid


def test_needs_its_own_tick(client, db):
    order = _order(db)
    mina = staff(db, "operator", "mina")
    r = client.post("/admin/archive/orders", json={"ids": [order]}, headers=mina)
    assert r.status_code == 403
    assert db.get_order(order)["archived_at"] is None


def test_the_manager_archives_anyones_finished_order_at_once(client, db):
    boss = staff(db, "super_admin", "boss")
    written = _order(db, "written")
    sent = _order(db, "approved", shipped_at="2026-02-01")
    cancelled = _order(db, "cancelled")
    open_one = _order(db, "awaiting_payment")
    waiting = _order(db, "approved", accounting_pending=1)
    r = client.post("/admin/archive/orders", headers=boss,
                    json={"ids": [written, sent, cancelled, open_one, waiting]}).json()
    assert r == {"archived": [written, sent, cancelled], "refused": [open_one, waiting]}
    assert db.get_order(written)["archived_at"] is not None
    assert db.get_order(open_one)["archived_at"] is None


def test_restore_and_archived_stay_in_reports_and_search(client, db):
    boss = staff(db, "super_admin", "boss")
    order = _order(db, "written")
    client.post("/admin/archive/orders", json={"ids": [order]}, headers=boss)
    listed = client.get("/admin/orders", params={"status": "written"}, headers=boss).json()
    assert [o["id"] for o in listed] == []
    listed = client.get("/admin/orders", params={"status": "written", "include_archived": True},
                        headers=boss).json()
    assert [o["id"] for o in listed] == [order]
    assert listed[0]["archived_at"]
    archived = client.get("/admin/archive/orders", params={"q": str(order)}, headers=boss).json()
    assert [o["id"] for o in archived] == [order]
    r = client.post("/admin/archive/orders/restore", json={"ids": [order]}, headers=boss).json()
    assert r == {"restored": [order], "refused": []}
    assert db.get_order(order)["archived_at"] is None
    assert client.post("/admin/archive/orders/restore", json={"ids": [order]},
                       headers=boss).json() == {"restored": [], "refused": [order]}


def test_a_sales_user_with_the_tick_can_too(client, db):
    from app import staff as staff_mod

    assert "archive_manual.edit" in staff_mod.ALL_PERMISSIONS
    assert "archive_manual.edit" not in staff_mod.PERMISSIONS[staff_mod.ROLE_SALES]


# ---- proxies ------------------------------------------------------------------------------------
def _pool(db, now=NOW) -> ProxyPool:
    return ProxyPool(db, clock=lambda: now)


def _add(pool, host, source="channel", **fields) -> int:
    row, _ = pool.add(ProxyLink(host, 443, SECRET), source, state=fields.pop("state", "probation"))
    for key, value in fields.items():
        pool.db._conn.execute(f"UPDATE proxies SET {key}=? WHERE id=?", (value, row["id"]))
    pool.db._conn.commit()
    return row["id"]


def _iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def test_a_collected_proxy_down_for_a_day_is_deleted(db):
    pool = _pool(db)
    _add(pool, "alive.example", last_ok_at=_iso(0.1))                # the network works
    old = _add(pool, "old.example", state="retired", added_at=_iso(30), last_fail_at=_iso(1))
    recent = _add(pool, "new.example", state="retired", added_at=_iso(2), last_fail_at=_iso(1))
    was_ok = _add(pool, "was.example", state="retired", added_at=_iso(90), last_ok_at=_iso(5),
                  last_fail_at=_iso(1))
    assert pool.prune_dead() == [old]
    assert pool.get(old) is None and pool.get(recent) and pool.get(was_ok)


def test_a_manual_proxy_is_never_deleted_by_itself(db):
    pool = _pool(db)
    _add(pool, "alive.example", last_ok_at=_iso(0.1))
    mine = _add(pool, "mine.example", source="manual", state="main", added_at=_iso(90),
                last_fail_at=_iso(1))
    assert pool.prune_dead() == [] and pool.get(mine)


def test_nothing_is_deleted_while_the_network_is_out(db):
    pool = _pool(db)
    old = _add(pool, "old.example", state="retired", added_at=_iso(90), last_fail_at=_iso(1))
    assert pool.prune_dead() == [] and pool.get(old)


@pytest.mark.parametrize("path,kept", [("/admin/proxies/delete-down", {"alive.example"})])
def test_delete_all_down_and_selected(client, db, path, kept):
    boss = staff(db, "super_admin", "boss")
    pool = ProxyPool(db)
    alive = _add(pool, "alive.example", last_ok_at=_iso(0.1))
    _add(pool, "dead.example", state="retired")
    _add(pool, "mine.example", source="manual", last_fail_at=_iso(1))
    assert client.post(path, headers=boss).json() == {"deleted": 2}
    assert {p["host"] for p in pool.list_all()} == kept
    assert client.post("/admin/proxies/delete", json={"ids": [alive]},
                       headers=boss).json() == {"deleted": 1}


def test_the_list_says_where_a_proxy_came_from(client, db):
    boss = staff(db, "super_admin", "boss")
    pool = ProxyPool(db)
    _add(pool, "collected.example", source="channel:ProxyMTProto")
    _add(pool, "mine.example", source="manual")
    rows = {p["host"]: p["source"] for p in client.get("/admin/proxies", headers=boss).json()}
    assert rows == {"collected.example": "channel:ProxyMTProto", "mine.example": "manual"}


def test_deleting_needs_the_tick(client, db):
    mina = staff(db, "operator", "mina")
    assert client.post("/admin/proxies/delete-down", headers=mina).status_code == 403
    assert client.get("/admin/proxies", headers=h("site")).status_code in (401, 403)
