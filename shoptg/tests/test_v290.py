"""v2.9.0: Telegram Desktop key preset, device parameters, login from ShopAdmin."""
from __future__ import annotations

import asyncio
import json

import pytest

from app import config
from app.config import TDESKTOP_API_HASH, TDESKTOP_API_ID, Settings
from app.gateway import TelegramGateway
from app.login_flow import LoginFlow, run_pipe
from fakes import FakeTelegram, pool_entry


def run(coro):
    return asyncio.run(coro)


def _clear(monkeypatch):
    for key in ("TG_API_ID", "TG_API_HASH", "TG_API_PRESET", "TG_PROXY_CHANNELS",
                "TG_PROXY_COLLECT_DAYS", "TG_PROXY_COLLECT_HOURS", "TG_DEVICE_MODEL",
                "TG_PROXY_POOL_SIZE"):
        monkeypatch.delenv(key, raising=False)


# ---- settings ----------------------------------------------------------------------
def test_without_own_key_the_telegram_desktop_key_is_used(monkeypatch):
    _clear(monkeypatch)
    s = Settings.from_env(load_file=False)
    assert s.api_preset == "tdesktop"
    assert (s.api_id, s.api_hash) == (TDESKTOP_API_ID, TDESKTOP_API_HASH)
    assert s.missing() == ["WORKER_API_KEY"]
    assert TDESKTOP_API_HASH not in repr(s)
    device = s.device()
    assert device["lang_pack"] == "tdesktop" and device["system_version"].startswith("Windows")
    assert device["device_model"] == "Desktop" and device["app_version"].endswith("x64")


def test_own_key_and_switching_back(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TG_API_ID", "123456")
    monkeypatch.setenv("TG_API_HASH", "a" * 32)
    s = Settings.from_env(load_file=False)
    assert (s.api_preset, s.api_id) == ("custom", 123456)
    assert s.device()["lang_pack"] == ""
    monkeypatch.setenv("TG_API_PRESET", "tdesktop")      # kept own values, chose the preset
    assert Settings.from_env(load_file=False).api_id == TDESKTOP_API_ID
    monkeypatch.setenv("TG_API_PRESET", "custom")
    monkeypatch.delenv("TG_API_HASH")
    assert "TG_API_HASH" in Settings.from_env(load_file=False).missing()
    monkeypatch.setenv("TG_API_PRESET", "other")
    with pytest.raises(ValueError):
        Settings.from_env(load_file=False)


def test_device_overrides(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TG_DEVICE_MODEL", "MS-7C02")
    assert Settings.from_env(load_file=False).device()["device_model"] == "MS-7C02"


def test_proxy_pool_defaults(monkeypatch):
    _clear(monkeypatch)
    s = Settings.from_env(load_file=False)
    assert s.proxy_channels == ["ProxyMTProto"]
    assert s.proxy_collect_hours == 24 and s.pool_size == 5 and s.web_preview
    monkeypatch.setenv("TG_PROXY_CHANNELS", "none")
    assert Settings.from_env(load_file=False).proxy_channels == []
    monkeypatch.setenv("TG_PROXY_COLLECT_DAYS", "7")       # the old setting still works
    assert Settings.from_env(load_file=False).proxy_collect_hours == 168


def test_shopsystem_child_never_reads_a_dotenv(monkeypatch):
    monkeypatch.delenv("SHOPTG_NO_DOTENV", raising=False)
    assert not config.dotenv_disabled()
    monkeypatch.setenv("SHOPTG_NO_DOTENV", "1")
    assert config.dotenv_disabled()


# ---- gateway --------------------------------------------------------------------------
def test_real_telethon_client_gets_the_desktop_parameters():
    s = Settings(api_preset="tdesktop", api_id=TDESKTOP_API_ID, api_hash=TDESKTOP_API_HASH)

    async def build():
        client = TelegramGateway(s.api_id, s.api_hash, device=s.device()).make_client("", None)
        init = client._init_request
        return init.device_model, init.system_version, init.app_version, init.lang_pack, \
            init.lang_code, init.system_lang_code
    model, system, app_version, lang_pack, lang, system_lang = run(build())
    assert (model, lang_pack, lang, system_lang) == ("Desktop", "tdesktop", "en", "en-US")
    assert system == "Windows 10" and app_version.endswith("x64")


def test_fake_client_receives_device_kwargs():
    tg = FakeTelegram()
    gw = TelegramGateway(1, "h", client_factory=tg.factory, device={"device_model": "Desktop",
                                                                    "lang_pack": "tdesktop"})
    gw.make_client("", None)
    kwargs = tg.clients[-1].kwargs
    assert kwargs["device_model"] == "Desktop" and "lang_pack" not in kwargs


# ---- login flow -------------------------------------------------------------------------
@pytest.fixture
def flow_env(settings):
    tg = FakeTelegram()
    saved = {}
    gw = TelegramGateway(settings.api_id, settings.api_hash, timeout=2, client_factory=tg.factory)

    def save(path, session, account):
        saved.update(path=path, session=session, account=account)
    flow = LoginFlow(settings, gateway=gw, save=save)
    return flow, tg, saved


def test_login_code_then_done(flow_env, settings):
    flow, tg, saved = flow_env
    events = run(flow.start("+98 912 000 0000"))
    assert [e["event"] for e in events] == ["connected", "code_sent"]
    assert events[0]["via"] == "direct"
    assert run(flow.code("00000"))[0]["code"] == "code_invalid"
    assert run(flow.code("1 2 3 4 5")) == [{"event": "done"}]
    assert saved["session"] == "1FAKE-SESSION-STRING" and saved["path"] == settings.session_file


def test_login_with_two_step_password(flow_env):
    flow, tg, saved = flow_env
    tg.password = "secret-pass"
    run(flow.start("+989120000000"))
    assert run(flow.code("12345")) == [{"event": "password_needed"}]
    wrong = run(flow.password("nope"))[0]
    assert wrong["code"] == "password_invalid" and wrong["retry"] and wrong["left"] == 2
    assert run(flow.password("secret-pass")) == [{"event": "done"}]
    assert saved


def test_login_tries_typed_proxy_then_pool_then_direct(settings):
    tg = FakeTelegram()
    tg.dead_proxies.add(("typed.example", 443))

    async def pool():
        return [pool_entry(1, "pool.example")]
    gw = TelegramGateway(settings.api_id, settings.api_hash, timeout=2, client_factory=tg.factory)
    flow = LoginFlow(settings, gateway=gw, pool=pool, save=lambda *a: None)
    typed = f"tg://proxy?server=typed.example&port=443&secret=dd{'ab' * 16}"
    events = run(flow.start("+989120000000", typed))
    assert events[0] == {"event": "connected", "via": "pool.example:443 (dd)"}
    tg.direct_ok = False
    tg.dead_proxies.add(("pool.example", 443))
    assert run(flow.start("+989120000000", typed)) == [
        {"event": "error", "code": "no_connection", "retry": True}]


def test_login_short_phone_and_wrong_order(flow_env):
    flow, _, _ = flow_env
    assert run(flow.start("123"))[0]["code"] == "phone_invalid"
    assert run(flow.code("12345"))[0]["code"] == "bad_state"


def test_pipe_protocol_never_echoes_secrets(flow_env, settings):
    flow, tg, saved = flow_env
    tg.password = "pw-123"
    lines = iter([json.dumps({"cmd": "start", "phone": "+989120000000"}) + "\n",
                  json.dumps({"cmd": "code", "code": "12345"}) + "\n",
                  "not json\n",
                  json.dumps({"cmd": "password", "password": "pw-123"}) + "\n"])
    out: list[dict] = []
    code = run(run_pipe(settings, read=lambda: next(lines, ""), write=out.append, flow=flow))
    assert code == 0
    events = [e["event"] for e in out]
    assert events == ["ready", "connected", "code_sent", "password_needed", "error", "done"]
    text = json.dumps(out)
    assert "pw-123" not in text and "12345" not in text and "989120000000" not in text
    assert out[0]["preset"] == "custom" and saved


def test_pipe_cancel_and_end_of_input(flow_env, settings):
    flow, _, _ = flow_env
    lines = iter([json.dumps({"cmd": "cancel"}) + "\n"])
    assert run(run_pipe(settings, read=lambda: next(lines, ""), write=lambda e: None,
                        flow=flow)) == 1
    assert run(run_pipe(settings, read=lambda: "", write=lambda e: None, flow=flow)) == 1


def test_the_key_chosen_in_the_form_is_used_for_the_login(flow_env, settings):
    flow, tg, saved = flow_env
    assert flow.use_key("tdesktop")
    assert (flow.s.api_preset, flow.s.api_id) == ("tdesktop", TDESKTOP_API_ID)
    assert flow.tg._device["lang_pack"] == "tdesktop"
    run(flow.start("+989120000000"))
    assert tg.clients[-1].kwargs["device_model"] == "Desktop"     # the fake factory is kept
    assert not flow.use_key("custom")                  # no own key saved, none typed
    assert flow.use_key("custom", "777", "b" * 32) and flow.s.api_id == 777


def test_pipe_refuses_a_custom_key_without_values(flow_env, settings):
    flow, _, _ = flow_env
    flow.s.api_preset = "tdesktop"
    lines = iter([json.dumps({"cmd": "start", "phone": "+989120000000", "preset": "custom"}) + "\n"])
    out: list[dict] = []
    run(run_pipe(settings, read=lambda: next(lines, ""), write=out.append, flow=flow))
    assert out[-1]["code"] == "api_missing"
