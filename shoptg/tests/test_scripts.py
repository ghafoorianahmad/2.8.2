"""scripts/login.py and scripts/check_pricelist.py with the fake Telethon."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from app.gateway import TelegramGateway
from fakes import FakeTelegram, fake_message

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT.parent / "samples" / "price_list.pdf"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"script_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Prompts:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def __call__(self, prompt, **_):
        self.asked.append(prompt)
        return self.answers.pop(0)


@pytest.fixture
def login_env(monkeypatch, settings):
    mod = load_script("login")
    tg = FakeTelegram()
    saved = {}
    monkeypatch.setattr(mod, "TelegramGateway",
                        lambda *a, **k: TelegramGateway(*a, client_factory=tg.factory, **k))
    monkeypatch.setattr(mod, "choose_proxies", lambda s: [None])
    monkeypatch.setattr(mod.secure_store, "save_session",
                        lambda path, session, account: saved.update(path=path, session=session))
    return mod, tg, saved


def test_login_saves_encrypted_session_and_prints_no_secret(login_env, settings, monkeypatch, capsys):
    mod, tg, saved = login_env
    prompts = Prompts("+989120000000", "000", "12345")
    monkeypatch.setattr(mod, "hidden", prompts)
    assert asyncio.run(mod.login(settings)) == 0
    assert saved == {"path": settings.session_file, "session": "1FAKE-SESSION-STRING"}
    out = capsys.readouterr().out
    assert "Wrong code (1/3)" in out and "Login OK" in out
    for secret in ("+989120000000", "12345", "1FAKE-SESSION-STRING"):
        assert secret not in out
    assert all("hidden" in p for p in prompts.asked)
    assert not tg.clients[0].connected                # disconnected afterwards


def test_login_with_two_step_password(login_env, settings, monkeypatch, capsys):
    mod, tg, saved = login_env
    tg.password = "pw-2fa"
    monkeypatch.setattr(mod, "hidden", Prompts("+98912", "12345", "wrong", "pw-2fa"))
    assert asyncio.run(mod.login(settings)) == 0
    assert saved["session"] == "1FAKE-SESSION-STRING"
    out = capsys.readouterr().out
    assert "Wrong password." in out and "pw-2fa" not in out


def test_login_gives_up_after_three_wrong_codes(login_env, settings, monkeypatch):
    mod, tg, saved = login_env
    monkeypatch.setattr(mod, "hidden", Prompts("+98912", "1", "2", "3"))
    assert asyncio.run(mod.login(settings)) == 1
    assert saved == {}


def test_login_without_connection(login_env, settings, monkeypatch):
    mod, tg, saved = login_env
    tg.direct_ok = False
    monkeypatch.setattr(mod, "hidden", Prompts())
    assert asyncio.run(mod.login(settings)) == 1
    assert saved == {}


def test_choose_proxies_prompts_hidden_and_validates(settings, capsys):
    from app.interactive import choose_proxies
    good = "tg://proxy?server=p.example&port=443&secret=dd" + "ab" * 16
    prompts = Prompts("not a link", good)
    links = choose_proxies(settings, reader=prompts)
    assert links[0].host == "p.example" and len(prompts.asked) == 2
    assert "ab" * 16 not in capsys.readouterr().out
    assert choose_proxies(settings, reader=Prompts("")) == [None]
    settings.local_proxies = [good]
    assert choose_proxies(settings, reader=Prompts())[0].host == "p.example"


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample PDF not in the tree")
def test_check_pricelist_downloads_and_parses_the_newest_pdf(settings, tmp_path):
    mod = load_script("check_pricelist")
    tg = FakeTelegram()
    pdf = SAMPLE.read_bytes()
    tg.channels[settings.price_channel] = [fake_message(40, pdf=b"%PDF old"),
                                           fake_message(41, pdf=pdf), fake_message(42, image=True)]
    gw = TelegramGateway(1, "h", timeout=5, client_factory=tg.factory)
    lines = []
    code = asyncio.run(mod.check(settings, scan=50, save=True, proxy_channels=False, gateway=gw,
                                 session="S", links=[None], out=lines.append))
    text = "\n".join(lines)
    assert code == 0, text
    assert "Newest PDF: message 41" in text and "List date      : 1405/07/19" in text
    assert "Rows           : 195" in text and "download:41" in tg.calls
    assert (settings.data_dir / "check_41.pdf").read_bytes() == pdf
    assert not gw.connected


def test_check_pricelist_reports_a_parse_failure(settings):
    mod = load_script("check_pricelist")
    tg = FakeTelegram()
    tg.channels[settings.price_channel] = [fake_message(5, pdf=b"%PDF-1.4 broken")]
    gw = TelegramGateway(1, "h", timeout=5, client_factory=tg.factory)
    lines = []
    code = asyncio.run(mod.check(settings, scan=10, save=False, proxy_channels=False, gateway=gw,
                                 session="S", links=[None], out=lines.append))
    assert code == 2 and "PARSE FAILED" in "\n".join(lines)


def test_check_pricelist_counts_proxy_links(settings):
    mod = load_script("check_pricelist")
    tg = FakeTelegram()
    tg.channels[settings.price_channel] = [fake_message(5, pdf=SAMPLE.read_bytes())]
    tg.channels["ProxyChan"] = [fake_message(1, text="tg://proxy?server=a.example&port=1&secret=dd"
                                             + "ab" * 16)]
    gw = TelegramGateway(1, "h", timeout=5, client_factory=tg.factory)
    lines = []
    asyncio.run(mod.check(settings, scan=10, save=False, proxy_channels=True, gateway=gw,
                          session="S", links=[None], out=lines.append))
    assert "@ProxyChan: 1 messages, 1 proxy links {'dd': 1}" in lines
