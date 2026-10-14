from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from app import secure_store
from app.config import Settings, channel_username
from app.gateway import NotAuthorized, TelegramGateway, to_message
from tgproxy import extract_links, from_pool, parse_proxy_link
from fakes import SECRET16, FakeTelegram, fake_message

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


def run(coro):
    return asyncio.run(coro)


# ---- secure store ---------------------------------------------------------------------------
@windows_only
def test_dpapi_round_trip_and_magic(tmp_path):
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    path = tmp_path / "s" / "tg_session.dpapi"
    secure_store.save_session(path, "1AbC-session", "SHOP\\svc_shop", runner=runner)
    raw = path.read_bytes()
    assert raw.startswith(secure_store.MAGIC) and b"1AbC-session" not in raw
    assert secure_store.load_session(path) == "1AbC-session"
    # folder then file; SIDs, not localized names; read-only grant for the service account
    folder_args, file_args = calls
    assert folder_args[:3] == ["icacls", str(path.parent), "/inheritance:r"]
    assert "*S-1-5-18:(OI)(CI)(F)" in folder_args and "SHOP\\svc_shop:(OI)(CI)(RX)" in folder_args
    assert file_args == ["icacls", str(path), "/inheritance:r", "/grant:r",
                         "*S-1-5-18:(F)", "*S-1-5-32-544:(F)", "SHOP\\svc_shop:(R)"]
    assert not path.with_suffix(".dpapi.tmp").exists()


@windows_only
def test_tampered_blob_is_refused(tmp_path):
    path = tmp_path / "x.dpapi"
    path.write_bytes(secure_store.MAGIC + secure_store.protect(b"abc")[:-3] + b"xyz")
    with pytest.raises(secure_store.SecureStoreError):
        secure_store.load_session(path)


def test_missing_or_foreign_file(tmp_path):
    with pytest.raises(secure_store.SecureStoreError, match="login"):
        secure_store.load_session(tmp_path / "none")
    (tmp_path / "f").write_bytes(b"plain text session")
    with pytest.raises(secure_store.SecureStoreError, match="format"):
        secure_store.load_session(tmp_path / "f")


def test_icacls_failure_is_reported(tmp_path):
    with pytest.raises(secure_store.SecureStoreError, match="Administrator"):
        secure_store.restrict_acl(tmp_path, runner=lambda *a, **k: SimpleNamespace(returncode=5))


# ---- config / proxies -----------------------------------------------------------------------
def test_channel_username_forms():
    for raw in ("https://t.me/AbrishamiiPhoneMashhad", "t.me/s/AbrishamiiPhoneMashhad",
                "@AbrishamiiPhoneMashhad", "AbrishamiiPhoneMashhad/123"):
        assert channel_username(raw) == "AbrishamiiPhoneMashhad"
    with pytest.raises(ValueError):
        channel_username("https://t.me/+invitehash")


def test_settings_from_env(monkeypatch, tmp_path):
    for key, value in {"TG_API_ID": "123", "TG_API_HASH": "abc", "WORKER_API_KEY": "k",
                       "TG_PROXY_CHANNELS": "@chan_one, https://t.me/chan_two", "TG_DATA_DIR": str(tmp_path),
                       "TG_PRICE_INTERVAL_MIN": "1", "TG_PROXY": "tg://a tg://b"}.items():
        monkeypatch.setenv(key, value)
    s = Settings.from_env(load_file=False)
    assert s.api_id == 123 and s.proxy_channels == ["chan_one", "chan_two"]
    assert s.price_interval_sec == 300        # never more often than 5 minutes
    assert s.local_proxies == ["tg://a", "tg://b"] and s.missing() == []
    assert "abc" not in repr(s) and "tg://a" not in repr(s)
    monkeypatch.setenv("TG_API_ID", "12x")
    with pytest.raises(ValueError):
        Settings.from_env(load_file=False)


def test_proxy_links_parse_like_shopapi():
    dd = parse_proxy_link(f"https://t.me/proxy?server=Host.Example&port=443&secret=dd{SECRET16}")
    assert (dd.host, dd.kind) == ("host.example", "dd")
    ee = parse_proxy_link("tg://proxy?server=h.example&port=443&secret=ee" + SECRET16
                          + b"cdn.example.com".hex())
    assert ee.kind == "ee" and ee.tls_domain == "cdn.example.com"
    assert parse_proxy_link("tg://proxy?server=h&port=443&secret=ee" + SECRET16) is None
    assert parse_proxy_link("tg://proxy?server=h&port=99999&secret=" + SECRET16) is None
    assert parse_proxy_link("tg://socks?server=h&port=1") is None
    assert SECRET16 not in repr(dd) and "host.example:443 (dd)" in repr(dd)
    text = f"a tg://proxy?server=x.example&port=1&secret={SECRET16}. b"
    assert extract_links([text, text]) == [f"tg://proxy?server=x.example&port=1&secret={SECRET16}"]
    assert from_pool({"id": 3, "host": "h", "port": "443", "secret": SECRET16}).id == 3
    assert from_pool({"id": 3}) is None


def test_connection_class_per_secret_kind():
    from telethon.network.connection import (
        ConnectionTcpMTProxyIntermediate,
        ConnectionTcpMTProxyRandomizedIntermediate,
    )
    from tgproxy.connection import connection_for
    from tgproxy.faketls import ConnectionTcpMTProxyFakeTLS
    assert connection_for(None) == {}
    for secret, cls in ((SECRET16, ConnectionTcpMTProxyIntermediate),
                        ("dd" + SECRET16, ConnectionTcpMTProxyRandomizedIntermediate),
                        ("ee" + SECRET16 + b"a.com".hex(), ConnectionTcpMTProxyFakeTLS)):
        link = parse_proxy_link(f"tg://proxy?server=h.example&port=443&secret={secret}")
        kwargs = connection_for(link)
        assert kwargs["connection"] is cls and kwargs["proxy"] == ("h.example", 443, secret)


def test_real_telethon_client_accepts_our_options():
    """The kwargs we pass exist in the installed Telethon (no network: never connected)."""
    async def build():
        gw = TelegramGateway(1, "0" * 32)
        link = parse_proxy_link("tg://proxy?server=h.example&port=443&secret=ee" + SECRET16
                                + b"a.com".hex())
        client = gw.make_client("", link)
        assert not client.is_connected()
        return client
    run(build())


# ---- gateway with the fake Telethon ---------------------------------------------------------
def make(tg: FakeTelegram) -> TelegramGateway:
    return TelegramGateway(1, "h", timeout=2, client_factory=tg.factory, clock=lambda: 0.0)


def test_connect_requires_authorized_session():
    tg = FakeTelegram()
    gw = make(tg)
    assert run(gw.connect("SESSION", None)) == 0 and gw.connected
    run(gw.disconnect())
    tg.authorized = False
    with pytest.raises(NotAuthorized):
        run(gw.connect("SESSION", None))
    assert not gw.connected and not tg.clients[-1].connected


def test_messages_oldest_first_and_pdf_detection():
    tg = FakeTelegram()
    tg.channels["chan"] = [fake_message(3, pdf=b"%PDF"), fake_message(1, image=True),
                           fake_message(2, text="hi", urls=["tg://x"])]
    gw = make(tg)

    async def scenario():
        await gw.connect("S", None)
        msgs = await gw.messages("chan", min_id=1, limit=10)
        data = await gw.download(msgs[-1], 1000)
        return msgs, data
    msgs, data = run(scenario())
    assert [m.id for m in msgs] == [2, 3]
    assert [m.is_pdf for m in msgs] == [False, True] and msgs[0].urls == ["tg://x"]
    assert data == b"%PDF"


def test_download_limit_and_not_connected():
    tg = FakeTelegram()
    gw = make(tg)
    msg = to_message(fake_message(1, pdf=b"%PDF" * 100))
    with pytest.raises(ConnectionError):
        run(gw.download(msg, 10))

    async def scenario():
        await gw.connect("S", None)
        await gw.download(msg, 10)
    with pytest.raises(ValueError):
        run(scenario())


def test_image_document_is_not_a_pdf():
    assert not to_message(fake_message(1, image=True)).is_pdf
    named = fake_message(2, pdf=b"%PDF", name="LIST.PDF")
    named.file.mime_type = "application/octet-stream"
    assert to_message(named).is_pdf


def test_price_channel_is_polled_every_10_minutes_by_default(monkeypatch):
    """v2.5.0: sales windows follow the list, so new lists are picked up within 10 min."""
    monkeypatch.delenv("TG_PRICE_INTERVAL_MIN", raising=False)
    assert Settings().price_interval_sec == 600
    assert Settings.from_env(load_file=False).price_interval_sec == 600


def test_tests_never_read_a_real_env_file(tmp_path, monkeypatch):
    import os

    from app import config

    (tmp_path / ".env").write_text("TG_PRICE_INTERVAL_MIN=99\n", encoding="utf-8")
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.delenv("TG_PRICE_INTERVAL_MIN", raising=False)
    monkeypatch.delenv("SHOPTG_ENV", raising=False)
    assert Settings.from_env().price_interval_sec == 600
    assert "TG_PRICE_INTERVAL_MIN" not in os.environ
