"""v2.9.3: staff's message inside the price offer, staff cancel with a reason for
the customer, «دادن دسترسی به این دیتابیس» (grant_shop_app.sql from the setup),
and the site models read from the live site and mapped automatically."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import grant_access, site_catalog
from app.catalog_models import CatalogModelRepo
from app.config import Settings

from .conftest import h
from .test_phase3 import staff
from .test_v260 import events
from .test_v270 import _order
from .test_v280 import A55, PRO, _map, _request, _shop  # noqa: F401
from .test_v280 import shop  # noqa: F401 - fixture

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "grant_shop_app.sql"


# ---- price offer with staff's message ------------------------------------------------------
def test_offer_carries_staffs_message(shop, db):
    _map(db, "i17p-zaa-silver", PRO)
    req = _request(shop, row_key="i17p-zaa-silver")
    mina = staff(db, "operator", "mina")
    note = "  گارانتی   ۱۸ ماهه\n\nهمین امروز ارسال می‌شود "
    r = shop.post(f"/admin/item-requests/{req['id']}/offer", json={"note": note}, headers=mina)
    assert r.status_code == 200, r.text
    message = shop.get(f"/admin/item-requests/{req['id']}/messages", headers=mina).json()[-1]
    assert message["note"] == "گارانتی ۱۸ ماهه\nهمین امروز ارسال می‌شود"
    assert "جمع" not in message["text"]                       # one item: no total
    assert "پیام همراه" in message["text"]
    delivery = shop.get(f"/admin/item-request-messages/{message['id']}",
                        headers=h("admin")).json()
    assert delivery["note"] == message["note"] and delivery["purpose"] == "offer"


# ---- staff cancel ------------------------------------------------------------------------------
def test_staff_cancel_tells_the_customer_with_the_reason(client, reader, db):
    order_id = _order(client, reader)
    boss = staff(db, "super_admin", "boss")
    r = client.post(f"/admin/orders/{order_id}/cancel", json={"reason": "  رنگ   تمام شد "},
                    headers=boss)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and r.json()["cancel_note"] == "رنگ تمام شد"
    assert "order_cancelled_by_staff" in events(db)
    # without a body (older ShopAdmin) it still works
    other = _order(client, reader)
    assert client.post(f"/admin/orders/{other}/cancel", headers=boss).json()["cancel_note"] == ""


# ---- grant access ------------------------------------------------------------------------------
def test_grant_sql_is_the_script_file():
    assert grant_access.GRANT_SQL == SQL_FILE.read_text(encoding="utf-8")
    batches = grant_access.grant_batches("hesab5 t", "shopbot")
    assert len(batches) == 4 and "USE [hesab5 t];" in batches[0]
    assert "$(" not in "".join(batches)
    with pytest.raises(grant_access.GrantError):
        grant_access.grant_batches("hesab5]; DROP", "shopbot")
    with pytest.raises(grant_access.GrantError):
        grant_access.grant_batches("hesab5", "shop bot")


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._row = None

    def execute(self, sql, *params):
        self.conn.executed.append((sql, params))
        if sql.startswith("SELECT 1 FROM sys.server_principals"):
            self._row = (1,) if self.conn.login_exists else None
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError(*self.conn.fail_args)
        return self

    def fetchone(self):
        return self._row

    def nextset(self):
        return False


class FakeConn:
    def __init__(self, login_exists=True, fail_on="", fail_args=()):
        self.login_exists = login_exists
        self.fail_on = fail_on
        self.fail_args = fail_args
        self.executed = []
        self.closed = False
        self.string = ""

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


def _settings(**kw) -> Settings:
    base = dict(accounting_server=r".\SQLEXPRESS", accounting_database="hesab5",
                accounting_username="shopbot", accounting_password="S3cret!",
                accounting_trusted=False)
    base.update(kw)
    return Settings(**base)


def test_grant_creates_what_is_missing_with_the_admin_sign_in():
    conn = FakeConn(login_exists=False)

    def connect(string, **kwargs):
        conn.string = string
        assert kwargs.get("autocommit") is True
        return conn

    result = grant_access.grant_shop_app(_settings(), connect)
    assert "Trusted_Connection=yes" in conn.string and "DATABASE=master" in conn.string
    assert "UID=" not in conn.string and "S3cret" not in conn.string
    assert result["steps"] == ["login_created", "user_ready", "role_granted"]
    create = next(sql for sql, _ in conn.executed if "CREATE LOGIN" in sql)
    assert "S3cret" not in create                     # the password is a parameter
    assert any(params and "S3cret!" in params for _sql, params in conn.executed)
    assert conn.closed


def test_grant_for_windows_sign_in_and_db_owner():
    conn = FakeConn(login_exists=True, fail_on="EXEC sp_addrolemember",
                    fail_args=("42000", "[42000] NT SERVICE\\ShopServer is db_owner: remove it"))
    result = grant_access.grant_shop_app(_settings(accounting_trusted=True),
                                         lambda s, **k: conn)
    assert result["login"] == grant_access.SERVICE_LOGIN and result["note"] == "db_owner"


def test_grant_without_sysadmin_says_so():
    conn = FakeConn(fail_on="CREATE ROLE",
                    fail_args=("42000", "[42000] CREATE ROLE permission denied (15247)"))
    with pytest.raises(grant_access.GrantError) as raised:
        grant_access.grant_shop_app(_settings(), lambda s, **k: conn)
    assert "sysadmin" in raised.value.message_fa
    with pytest.raises(grant_access.GrantError):
        grant_access.grant_shop_app(_settings(accounting_username="sa"), lambda s, **k: conn)


# ---- site models ---------------------------------------------------------------------------------
SITE_JS = """
const CATALOG = {
  apple: {
    name: "Apple", mark: "apple", tagline: "x",
    items: [
      { id: "iphone-17-pro-max", name: "iPhone 17 Pro Max", tier: "پرچمدار",
        aliases: ["آیفون ۱۷ پرو مکس"], spec: { "x": "y" } },
      { id: "iphone-17-pro", name: "iPhone 17 Pro", aliases: [] },
      { id: "iphone-17", name: "iPhone 17", aliases: [] },
      { id: "iphone-air", name: "iPhone Air", aliases: [] }
    ]
  },
  samsung: {
    name: "Samsung", mark: "samsung", tagline: "x",
    items: [
      { id: "galaxy-s26-ultra", name: "Galaxy S26 Ultra", aliases: [] },
      { id: "galaxy-a55", name: "Galaxy A55", aliases: [] },
      { id: "galaxy-a56", name: "Galaxy A56", aliases: [] }
    ]
  },
  accessories: {
    name: "Accessories", mark: "acc", tagline: "x",
    items: [
      { id: "anker-charger-65w", name: "Anker Charger 65W", kind: "accessory", aliases: [] }
    ]
  }
};
"""


def test_parse_site_catalog():
    models = site_catalog.parse_products_js(SITE_JS)
    assert [m["slug"] for m in models][:2] == ["iphone-17-pro-max", "iphone-17-pro"]
    assert models[0]["brand"] == "Apple" and models[0]["aliases"] == ["آیفون ۱۷ پرو مکس"]
    assert models[-1]["kind"] == "accessory" and models[0]["kind"] == "phone"


@pytest.mark.parametrize("name, brand, description, section, verdict", [
    ("iPhone 17 Pro Max", "apple", "17 Promax 256 ZAA", "iPHONE", "sure"),
    ("iPhone 17 Pro", "apple", "17 Promax 256 ZAA", "iPHONE", ""),       # Max is another model
    ("iPhone 17", "apple", "17 Pro 256 ZAA", "iPHONE", ""),
    ("iPhone 17", "apple", "17 256 CHA", "iPHONE", "sure"),
    ("iPhone Air", "apple", "Macbook Air (M4) 256 R16 15\"", "MACBOOK", ""),   # not a phone
    ("Galaxy A16", "samsung", "iPad 11 (A16) WIFI 10.9\" 128", "IPAD & PEN", ""),
    ("Galaxy S25", "samsung", "S25 FE 256GB Ram8", "SAMSUNG", ""),
    ("Galaxy A56", "samsung", "A56 256GB Ram8", "SAMSUNG", "sure"),
    ("Redmi Note 15", "xiaomi", "Redmi Note 15 256GB Ram8", "XIAOMI", "sure"),
    ("Redmi 15", "xiaomi", "Redmi Note 15 256GB Ram8", "XIAOMI", ""),
    ("Redmi Note 14", "xiaomi", "Redmi Note 14S 256GB Ram8", "XIAOMI", ""),
    ("Redmi Note 15 Pro+", "xiaomi", "Redmi Note 15 Pro+ 5G 512GB Ram12", "XIAOMI", "sure"),
    ("Xiaomi 15", "xiaomi", "15 128", "iPHONE", ""),                   # another brand
])
def test_site_model_to_price_row(name, brand, description, section, verdict):
    row = {"section": section, "description": description, "kind": "", "color": "Black"}
    assert site_catalog.row_matches(name, brand, row) == verdict


def _rows(db):
    from app.purchase import active_rows

    return active_rows(db, Settings())[1]


def test_read_site_maps_phones_through_the_price_list(shop, db, reader, settings):
    _map(db, "i17p-zaa-silver", PRO)
    _map(db, "a55-navy", A55)
    reader.products[900] = {"name": "شارژر انکر 65 وات Anker Charger 65W", "group": 1,
                            "stock": 1.0, "open": 0.0, "unit_price": 1.0, "image": None}
    summary = site_catalog.read_site(db, reader, settings, fetch=lambda url: SITE_JS)
    assert summary["ok"] and summary["found"] == 8 and summary["added"] == 8
    mapping = summary["mapping"]
    assert mapping["phones"] == 7 and mapping["accessories"] == 1
    repo = CatalogModelRepo(db)
    pro = repo.get_by_slug("iphone-17-pro")
    assert [i["kala_code"] for i in repo.items(pro["id"])] == [PRO]
    assert repo.items(pro["id"])[0]["label"] == "256 گیگ"
    assert pro["status"] == "ok" and pro["source"] == "site"
    a55 = repo.get_by_slug("galaxy-a55")
    assert [i["kala_code"] for i in repo.items(a55["id"])] == [A55]
    # S26 Ultra has a row, but the row is not mapped yet: nothing is guessed
    assert not repo.items(repo.get_by_slug("galaxy-s26-ultra")["id"])
    assert mapping["phones_no_mapping"] >= 1
    charger = repo.get_by_slug("anker-charger-65w")
    assert charger["kind"] == "accessory"
    assert "site_models_new" in events(db)
    assert site_catalog.last_read(db)["found"] == 8
    # read again: nothing new is announced, nothing is duplicated
    before = events(db).count("site_models_new")
    site_catalog.read_site(db, reader, settings, fetch=lambda url: SITE_JS)
    assert events(db).count("site_models_new") == before
    assert len(repo.items(pro["id"])) == 1


def test_uncertain_accessory_waits_for_a_manager(shop, db, reader, settings):
    reader.products[901] = {"name": "Anker Charger 45W", "group": 1, "stock": 1.0,
                            "open": 0.0, "unit_price": 1.0, "image": None}
    reader.products[902] = {"name": "Anker Charger 65W Pro", "group": 1, "stock": 1.0,
                            "open": 0.0, "unit_price": 1.0, "image": None}
    site_catalog.read_site(db, reader, settings, fetch=lambda url: SITE_JS)
    repo = CatalogModelRepo(db)
    charger = repo.get_by_slug("anker-charger-65w")
    assert not repo.items(charger["id"]) and charger["suggestions"]
    boss = staff(db, "super_admin", "boss")
    listed = shop.get("/admin/catalog-models", headers=boss).json()
    assert listed["counts"]["suggested"] >= 1 and listed["last_site_read"]["ok"]
    code = charger["suggestions"][0]["kala_code"]
    r = shop.post(f"/admin/catalog-models/{charger['id']}/suggestion/accept",
                  json={"kala_codes": [code]}, headers=boss)
    assert r.status_code == 200 and [i["kala_code"] for i in r.json()["items"]] == [code]
    assert repo.get_model(charger["id"])["suggestions"] == []


def test_read_site_now_endpoint_and_errors(shop, db, settings, monkeypatch):
    boss = staff(db, "super_admin", "boss")
    monkeypatch.setattr(site_catalog, "fetch_site", lambda url: SITE_JS)
    r = shop.post("/admin/catalog-models/read-site", headers=boss)
    assert r.status_code == 200 and r.json()["found"] == 8

    def down(url):
        raise RuntimeError("site unreachable (ConnectError)")

    monkeypatch.setattr(site_catalog, "fetch_site", down)
    r = shop.post("/admin/catalog-models/read-site", headers=boss)
    assert r.status_code == 502 and "unreachable" in r.json()["detail"]
    assert site_catalog.last_read(db)["ok"] is False
    mina = staff(db, "operator", "mina")
    assert shop.post("/admin/catalog-models/read-site", headers=mina).status_code == 403


def test_monthly_and_retry_rules(db):
    settings = Settings()
    assert settings.site_catalog_days == 30 and "asrertebatat2.ir" in settings.site_catalog_url
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    assert site_catalog.due(db, settings, now)
    db.set_state(site_catalog.LAST_READ_KEY,
                 json.dumps({"at": (now - timedelta(days=29)).isoformat(), "ok": True}), "t")
    assert not site_catalog.due(db, settings, now)
    assert site_catalog.due(db, settings, now + timedelta(days=1))
    db.set_state(site_catalog.LAST_READ_KEY,
                 json.dumps({"at": (now - timedelta(hours=25)).isoformat(), "ok": False}), "t")
    assert site_catalog.due(db, settings, now)


def test_a_new_price_list_maps_the_site_phones_again(shop, db, reader, settings):
    site_catalog.read_site(db, reader, settings, fetch=lambda url: SITE_JS)
    repo = CatalogModelRepo(db)
    ultra = repo.get_by_slug("galaxy-s26-ultra")
    assert not repo.items(ultra["id"])
    reader.products[777] = {"name": "سامسونگ S26 اولترا", "group": 3, "stock": 1.0,
                            "open": 0.0, "unit_price": 1.0, "image": None}
    _map(db, "s26u-black", 777)
    db.set_state(site_catalog.MAPPED_LIST_KEY, "", "t")
    assert site_catalog.remap_if_list_changed(db, reader, settings) is not None
    assert [i["kala_code"] for i in repo.items(ultra["id"])] == [777]
    assert site_catalog.remap_if_list_changed(db, reader, settings) is None   # same list
