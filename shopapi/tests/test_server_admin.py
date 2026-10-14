"""Server control endpoints (super admin only)."""
from __future__ import annotations

import pytest

from app import control

from .test_staff_auth import add_staff, bearer, login, owner_token


@pytest.fixture(autouse=True)
def clean_control():
    control.reset()
    yield
    control.reset()


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# shop server\n"
        "ACCOUNTING_SERVER=.\\SQLEXPRESS\n"
        "BANK_ACCOUNT_TEXT=old text\n"
        "BALE_TOKEN=123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd\n",
        encoding="utf-8",
    )
    control.set_files(env_file=path, log_file=tmp_path / "app.log")
    (tmp_path / "app.log").write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
    return path


def test_status_for_super_admin_only(client):
    owner = owner_token(client)
    add_staff(client, owner, "boss", "admin")
    boss = login(client, "boss").json()["token"]
    r = client.get("/admin/server/status", headers=bearer(owner))
    assert r.status_code == 200
    body = r.json()
    assert body["accounting"]["ok"] is True
    assert body["counts"]["staff"] == 2
    assert body["restart_available"] is False  # no launcher in tests
    assert client.get("/admin/server/status", headers=bearer(boss)).status_code == 403


def test_status_reports_accounting_down_without_failing(client, reader):
    owner = owner_token(client)
    reader.down = True
    body = client.get("/admin/server/status", headers=bearer(owner)).json()
    assert body["accounting"]["ok"] is False and body["accounting"]["error"] == "RuntimeError"
    assert body["accounting"]["message_fa"]          # v2.5.0: Persian explanation


def test_status_includes_registered_components(client):
    owner = owner_token(client)
    control.register_status_provider("bots", lambda: {"bale": {"running": True}})
    control.register_status_provider("broken", lambda: 1 / 0)
    body = client.get("/admin/server/status", headers=bearer(owner)).json()
    assert body["components"]["bots"] == {"bale": {"running": True}}
    assert body["components"]["broken"] == {"error": "ZeroDivisionError"}


def test_service_key_cannot_control_the_server(client):
    from .conftest import h

    owner_token(client)
    assert client.get("/admin/server/status", headers=h("admin")).status_code == 403


def test_settings_hide_secrets(client, env_file):
    owner = owner_token(client)
    settings = client.get("/admin/server/settings", headers=bearer(owner)).json()["settings"]
    assert settings["BANK_ACCOUNT_TEXT"] == {"secret": False, "value": "old text"}
    assert settings["BALE_TOKEN"] == {"secret": True, "set": True}
    assert "TELEGRAM_TOKEN" not in settings
    assert "ABCDEFGH" not in str(settings)
    assert "ACCOUNTING_SERVER" not in settings


def test_settings_update_keeps_other_lines(client, env_file, db):
    owner = owner_token(client)
    r = client.put("/admin/server/settings", headers=bearer(owner), json={"values": {
        "BANK_ACCOUNT_TEXT": "کارت ۶۰۳۷ به نام فروشگاه",
        "RECEIPT_DEADLINE_MINUTES": "45",
        "BALE_TOKEN": "987654:ZYXWVUTSRQPONMLKJIHGFEDCBAzyxw",
    }})
    assert r.status_code == 200 and r.json()["restart_required"] is True
    text = env_file.read_text(encoding="utf-8")
    assert "# shop server" in text
    assert "ACCOUNTING_SERVER=.\\SQLEXPRESS" in text
    assert 'BANK_ACCOUNT_TEXT="کارت ۶۰۳۷ به نام فروشگاه"' in text
    assert "RECEIPT_DEADLINE_MINUTES=45" in text
    assert "BALE_TOKEN=987654:ZYXWVUTSRQPONMLKJIHGFEDCBAzyxw" in text
    from dotenv import dotenv_values

    assert dotenv_values(env_file)["BANK_ACCOUNT_TEXT"] == "کارت ۶۰۳۷ به نام فروشگاه"
    audit = " ".join(r["detail"] for r in db.list_audit())
    assert "987654" not in audit and "کارت" not in audit


@pytest.mark.parametrize("key,value", [
    ("ACCOUNTING_WRITE_ENABLED", "true"),
    ("ACCOUNTING_SERVER", "evil"),
    ("ADMIN_API_KEY", "x"),
    ("API_HOST", "0.0.0.0"),
    ("RECEIPT_DEADLINE_MINUTES", "0"),
    ("RECEIPT_DEADLINE_MINUTES", "abc"),
    ("SALES_MORNING_CLOSE", "25:00"),
    ("PRICE_LEVEL_BOT", "9"),
    ("BALE_TOKEN", "not-a-token"),
    ("ADMIN_CHAT_IDS", "bale:12; rm -rf"),
    ("ADMIN_CHAT_IDS", "telegram:12"),
    ("BANK_ACCOUNT_TEXT", "line1\nINJECTED=1"),
    ("PAYMENT_CARD_NUMBER", "1234"),
    ("PAYMENT_CARD_NUMBER", "6037-9911-2222-33ab"),
    ("PAYMENT_SHEBA", "IR12"),
    ("PAYMENT_SHEBA", "GB82WEST12345698765432"),
    ("PAYMENT_OWNER", "x" * 81),
    ("PROXY_URL", "socks5://127.0.0.1:10808"),
    ("TELEGRAM_PROXY", "socks5://127.0.0.1:10808"),
    ("TELEGRAM_TOKEN", "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd"),
])
def test_dangerous_or_invalid_settings_are_refused(client, env_file, key, value):
    owner = owner_token(client)
    before = env_file.read_text(encoding="utf-8")
    r = client.put("/admin/server/settings", headers=bearer(owner), json={"values": {key: value}})
    assert r.status_code == 422
    assert env_file.read_text(encoding="utf-8") == before


def test_settings_unavailable_without_launcher(client):
    owner = owner_token(client)
    assert client.get("/admin/server/settings", headers=bearer(owner)).status_code == 409


def test_logs_tail(client, env_file):
    owner = owner_token(client)
    body = client.get("/admin/server/logs?lines=10", headers=bearer(owner)).json()
    assert body["lines"] == ["line 1", "line 2", "line 3"]


def test_restart_calls_the_hook(client, db):
    import threading

    owner = owner_token(client)
    assert client.post("/admin/server/restart", headers=bearer(owner)).status_code == 409
    fired = threading.Event()
    control.set_restart_hook(fired.set)
    assert client.post("/admin/server/restart", headers=bearer(owner)).status_code == 200
    assert fired.wait(5)
    assert any(r["action"] == "server_restart" for r in db.list_audit())
