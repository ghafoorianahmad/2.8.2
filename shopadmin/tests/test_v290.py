"""v2.9.0: three palettes × light/dark/system × «جلوه‌ها», the payment form cursor,
the Telegram reader (login from «تنظیمات سرور», status and proxy pool on
«سرور فروشگاه», notifications)."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect  # noqa: E402

from app import notifications  # noqa: E402
from app import server_setup as setup  # noqa: E402
from app.statuses import ROLE_OPERATOR, ROLE_SUPER_ADMIN  # noqa: E402
from app.ui import theme, widgets  # noqa: E402

from .test_ui import make_context_with_role, ui_context  # noqa: E402,F401


def _look(app, palette: str, mode: str, effects: str) -> None:
    """The look's tokens and effects WITHOUT restyling the whole application (a
    global setStyleSheet over every widget earlier tests left alive is slow)."""
    theme.set_mode(mode, palette)
    theme.EFFECTS = theme.resolve_effects(effects)
    theme._install_effects(app)


@pytest.fixture
def keep_look(admin_qapp):
    """Tests that change the look put the default one back."""
    before = (theme.PALETTE, theme.MODE, theme.EFFECTS)
    yield admin_qapp
    _look(admin_qapp, *before)


class _StubApp:
    """Just what ``apply_theme`` calls on the application."""

    def __init__(self):
        self.sheet = ""
        self.filters = []

    def setPalette(self, _p): pass          # noqa: E704,N802

    def setFont(self, _f): pass             # noqa: E704,N802

    def setLayoutDirection(self, _d): pass  # noqa: E704,N802

    def setStyleSheet(self, sheet):         # noqa: N802
        self.sheet = sheet

    def installEventFilter(self, f):        # noqa: N802
        self.filters.append(f)

    def removeEventFilter(self, f):         # noqa: N802
        if f in self.filters:
            self.filters.remove(f)

    def allWidgets(self):                   # noqa: N802
        return []


def _contrast(foreground: str, background: str) -> float:
    def lum(color: str) -> float:
        def channel(v: int) -> float:
            c = v / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        color = color.lstrip("#")
        r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    a, b = lum(foreground), lum(background)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# ---- 1: palettes, modes, effects ---------------------------------------------------------------
def test_every_palette_has_every_token_in_both_modes():
    keys = set(theme.palette_tokens("ocean", "light"))
    for palette in theme.PALETTE_NAMES:
        for mode in ("light", "dark"):
            tokens = theme.palette_tokens(palette, mode)
            assert set(tokens) == keys, (palette, mode)
    assert theme.PALETTES["light"]["PRIMARY"] == "#1F6AE0"           # v2.7.0 name kept
    assert set(theme.PALETTE_LABELS) == set(theme.PALETTE_NAMES)


@pytest.mark.parametrize("palette", ("ocean", "aurora", "emerald"))
@pytest.mark.parametrize("mode", ("light", "dark"))
def test_white_text_and_accent_text_meet_wcag_aa(palette, mode):
    t = theme.palette_tokens(palette, mode)
    for fill in ("PRIMARY", "PRIMARY_DARK", "PRIMARY_PRESSED", "SIDEBAR_HOVER", "SIDEBAR_ACTIVE",
                 "SIDEBAR_ACTIVE2", "SIDEBAR_BG", "SIDEBAR_BG2"):
        assert _contrast("#FFFFFF", t[fill]) >= 4.5, (palette, mode, fill)
    for text, background in (("PRIMARY_TEXT", "SURFACE"), ("PRIMARY_TEXT", "PRIMARY_SOFT"),
                             ("PRIMARY_TEXT", "HOVER"), ("PRIMARY_TEXT", "SELECTED_BG"),
                             ("TEXT", "BACKGROUND"), ("TEXT", "GLOW"),
                             ("SIDEBAR_TEXT", "SIDEBAR_BG"), ("SIDEBAR_MUTED", "SIDEBAR_BG"),
                             ("SIDEBAR_TEXT", "SIDEBAR_BG2"), ("TEXT_MUTED", "SURFACE")):
        assert _contrast(t[text], t[background]) >= 4.5, (palette, mode, text, background)


def test_apply_theme_switches_palette_mode_and_effects(keep_look):
    stub = _StubApp()
    real_filter, theme._EFFECTS_FILTER = theme._EFFECTS_FILTER, None   # the app keeps its own
    used = theme.apply_theme(stub, "dark", palette="aurora", effects="simple")
    assert used == "simple" and theme.PALETTE == "aurora" and theme.MODE == "dark"
    assert theme.PRIMARY == "#5850D8" and theme.window_background() == theme.BACKGROUND
    assert "qlineargradient" not in stub.sheet.split("QPushButton {")[1].split("}")[0]
    assert not stub.filters                               # simple: no shadow filter
    theme.apply_theme(stub, "light", palette="emerald", effects="full")
    assert theme.PRIMARY == "#047857" and "qradialgradient" in theme.window_background()
    assert "qradialgradient" in stub.sheet and len(stub.filters) == 1
    assert theme.resolve_effects("auto") in ("full", "simple")
    theme._EFFECTS_FILTER = real_filter


def test_simple_effects_take_shadows_away_and_full_adds_them(keep_look):
    app = keep_look
    _look(app, "ocean", "light", "full")
    panel = widgets.Panel("آزمایش")
    primary = widgets.button("ذخیره", variant="primary")
    panel.body.addWidget(primary)
    panel.show()
    QApplication.processEvents()
    assert isinstance(panel.graphicsEffect(), QGraphicsDropShadowEffect)
    assert isinstance(primary.graphicsEffect(), QGraphicsDropShadowEffect)
    table_panel = widgets.Panel("جدول")
    table_panel.body.addWidget(widgets.DataTable(("ستون",)))
    table_panel.show()
    QApplication.processEvents()
    assert table_panel.graphicsEffect() is None          # never around a table
    _look(app, "ocean", "light", "simple")
    assert panel.graphicsEffect() is None and primary.graphicsEffect() is None
    card = widgets.StatCard("کارت")
    assert card.graphicsEffect() is None
    panel.close()
    table_panel.close()


def test_stat_card_follows_the_palette_chosen_at_start(keep_look):
    _look(keep_look, "emerald", "light", "full")
    card = widgets.StatCard("سفارش")
    assert card._accent == "#047857"


def test_picker_saves_per_computer_and_offers_a_restart(ui_context, keep_look, monkeypatch):
    from app.ui import appearance

    picker = appearance.AppearancePicker(ui_context.store)
    assert picker.values() == ("ocean", "light", "auto")
    assert set(picker.cards["palette"]) == {"ocean", "aurora", "emerald"}
    assert set(picker.cards["effects"]) == {"auto", "full", "simple"}
    picker.select(palette="aurora", mode="system", effects="simple")
    assert picker.has_changed() and picker.save()
    assert appearance.saved_look(ui_context.store) == ("aurora", "system", "simple")
    ui_context.store.set_setting("theme_palette", "neon")      # unknown -> default
    assert appearance.saved_look(ui_context.store)[0] == "ocean"
    restarted = []
    ui_context.restart_app = lambda: restarted.append(True)
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: True)
    appearance.offer_restart(None, ui_context)
    assert restarted == [True]


def test_everyone_chooses_the_look_in_notifications_and_appearance(ui_context, keep_look,
                                                                     monkeypatch):
    from app.ui.main_window import NotificationDialog

    asked = []
    monkeypatch.setattr(widgets, "confirm", lambda *a, **k: asked.append(a[1]) or False)
    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    context.restart_app = lambda: None
    dialog = NotificationDialog(context)
    dialog.appearance.select(palette="emerald", effects="full")
    dialog.save()
    assert ui_context.store.get_setting("theme_palette") == "emerald"
    assert asked == ["ظاهر برنامه"]


def test_option_cards_keep_one_weight_when_checked():
    sheet = theme.stylesheet("Tahoma")
    block = sheet.split("QPushButton#OptionCard:checked")[1].split("}")[0]
    assert "font-weight" not in block


# ---- 2: the payment form's cursor ---------------------------------------------------------------
def test_click_in_an_empty_card_field_goes_to_its_first_place(ui_context, admin_qapp):
    from app.ui.pages import orders as page_mod

    form = page_mod.PaymentInfoDialog(None, make_context_with_role(ui_context, ROLE_OPERATOR),
                                      {"id": 3, "total": 10})
    form.show()
    QApplication.processEvents()
    card, sheba, account = (form.inputs[k] for k in ("card_number", "sheba", "account_number"))
    assert isinstance(card, widgets.MaskedLineEdit) and isinstance(account, widgets.MaskedLineEdit)
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(card.width() - 12, card.height() // 2))
    assert card.cursorPosition() == 0
    QTest.keyClicks(card, "6037")
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(card.width() - 12, card.height() // 2))
    assert card.cursorPosition() == card.first_empty_position() == 5     # after "6037-"
    QTest.keyClicks(card, "9911")
    assert card.text().replace("-", "").startswith("60379911")
    # Sheba: "IR" is fixed, the first empty place is right after it
    QTest.mouseClick(sheba, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(sheba.width() - 12, sheba.height() // 2))
    assert sheba.cursorPosition() == 2
    form.close()


def test_tab_into_a_half_typed_field_goes_to_the_first_empty_place(ui_context, admin_qapp):
    from app.ui.pages import orders as page_mod

    form = page_mod.PaymentInfoDialog(None, make_context_with_role(ui_context, ROLE_OPERATOR),
                                      {"id": 4, "total": 10})
    form.show()
    card = form.inputs["card_number"]
    card.setText("60379911")
    card.jump_to_first_empty()
    assert card.cursorPosition() == 10
    card.setCursorPosition(0)
    card.focusInEvent(_FocusEvent(Qt.FocusReason.TabFocusReason))
    QApplication.processEvents()
    assert card.cursorPosition() == 10
    account = form.inputs["account_number"]
    account.setText("0123")
    assert account.first_empty_position() == 4                    # no mask: the end
    form.close()


def _FocusEvent(reason):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent

    return QFocusEvent(QEvent.Type.FocusIn, reason)


# ---- 3/4: «سرور فروشگاه»: the reader and the proxy pool ---------------------------------------------
def test_server_page_shows_the_reader_and_the_pool(ui_context, admin_qapp, fake_api):
    from app.ui.pages.server import ServerPage

    fake_api.proxies = [
        {"id": 1, "host": "1.2.3.4", "port": 443, "kind": "ee", "state": "main",
         "source": "manual", "last_ok_at": "2026-10-21T08:00:00+00:00", "failing_now": False,
         "last_latency_ms": 420},
        {"id": 2, "host": "5.6.7.8", "port": 443, "kind": "dd", "state": "probation",
         "source": "channel:ProxyMTProto", "last_ok_at": None, "last_fail_at": "x",
         "failing_now": True},
        {"id": 3, "host": "9.9.9.9", "port": 443, "kind": "dd", "state": "retired",
         "source": "channel:ProxyMTProto", "failing_now": True},
    ]
    page = ServerPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page.load()
    for _ in range(50):
        QApplication.processEvents()
        if page.proxy_table.rowCount():
            break
    assert page.proxy_table.rowCount() == 2                    # retired ones are not listed
    texts = [page.proxy_table.item(0, c).text() for c in range(6)]
    assert texts[0] == "1.2.3.4:443" and texts[5] == "دستی"
    assert page.proxy_table.item(1, 5).text() == "کانال @ProxyMTProto"
    reader = page.tg_labels["reader"].text()
    assert "Telegram Desktop" in reader
    assert "۳ پراکسی سالم از ۵" in page.tg_labels["pool"].text()
    assert "لیست تازه فعال شد" in page.tg_labels["price"].text()
    assert page.add_proxy_button.isVisibleTo(page)
    text = json.dumps([page.tg_labels[k].text() for k in page.tg_labels], ensure_ascii=False)
    assert "secret" not in text


def test_pool_text_warns_when_nothing_works():
    from app.ui.pages.server import telegram_details

    rows = telegram_details({"login_required": True, "at": None},
                            {"target": 5, "working": 0, "active": 2, "all_failing": True})
    assert rows["pool"][1] == theme.DANGER and "پراکسی دستی" in rows["pool"][0]
    assert "تنظیمات سرور" in rows["reader"][0]
    assert "هنوز" in rows["collect"][0]


# ---- 3: notifications ---------------------------------------------------------------------------
def test_new_list_from_telegram_is_announced_and_failures_warn():
    notice = notifications.notice_for({"kind": "pricelist_imported", "ref_id": 7, "actor": "worker"})
    assert notice is not None and "تلگرام" in notice.body and notice.target == ("pricelist", "")
    assert notifications.notice_for({"kind": "pricelist_imported", "actor": "owner"}) is None
    error = notifications.notice_for({"kind": "telegram_pricelist_error"})
    assert error.warning and error.target == ("pricelist", "")
    login = notifications.notice_for({"kind": "telegram_login_required"})
    assert "تنظیمات سرور" in login.body and login.target == ("server", "")


# ---- 3: the login from «تنظیمات سرور» ------------------------------------------------------------
class FakeLogin:
    """The ``ShopSystem.exe --tg-login`` process, answering like login_flow."""

    def __init__(self, script):
        self.script = list(script)
        self.sent: list[dict] = []
        self.opened = self.closed = False

    def open(self):
        self.opened = True
        return {"event": "ready"}

    def send(self, payload):
        self.sent.append(payload)
        return self.script.pop(0)

    def close(self):
        self.closed = True


def _settle(dialog, until):
    for _ in range(200):
        QApplication.processEvents()
        if until():
            return
        QTest.qWait(5)


def test_login_dialog_phone_code_password(admin_qapp):
    from app.ui.telegram_login import TelegramLoginDialog

    fake = FakeLogin([
        [{"event": "connected", "via": "x"}, {"event": "code_sent"}],
        [{"event": "error", "code": "code_invalid", "retry": True, "left": 2}],
        [{"event": "password_needed"}],
        [{"event": "done"}],
    ])
    dialog = TelegramLoginDialog(None, preset="tdesktop", proxy="tg://proxy?server=a",
                                 login_factory=lambda: fake)
    dialog.phone.setText("۰۹۱۲۱۲۳۴۵۶۷")
    dialog.next_step()
    _settle(dialog, lambda: dialog.step == dialog.STEP_CODE)
    assert fake.sent[0] == {"cmd": "start", "phone": "+989121234567",
                            "proxy": "tg://proxy?server=a", "preset": "tdesktop",
                            "api_id": "", "api_hash": ""}
    dialog.code.setText("11111")
    dialog.next_step()
    _settle(dialog, lambda: "۲ بار" in dialog.status.text())
    assert dialog.step == dialog.STEP_CODE and dialog.code.text() == ""
    dialog.code.setText("12345")
    dialog.next_step()
    _settle(dialog, lambda: dialog.step == dialog.STEP_PASSWORD)
    dialog.password.setText("pw")
    dialog.next_step()
    _settle(dialog, lambda: dialog.step == dialog.STEP_DONE)
    assert dialog.logged_in and dialog.password.text() == ""
    _settle(dialog, lambda: fake.closed)
    assert fake.closed
    dialog.close()


def test_login_dialog_starts_over_after_a_final_error(admin_qapp):
    from app.ui.telegram_login import TelegramLoginDialog, error_text

    fake = FakeLogin([[{"event": "error", "code": "no_connection", "retry": True}],
                      [{"event": "error", "code": "phone_banned", "retry": False}]])
    dialog = TelegramLoginDialog(None, login_factory=lambda: fake)
    dialog.phone.setText("+989121234567")
    dialog.next_step()
    _settle(dialog, lambda: "پراکسی" in dialog.status.text())
    assert dialog.step == dialog.STEP_PHONE and not fake.closed
    dialog.next_step()
    _settle(dialog, lambda: "مسدود" in dialog.status.text())
    _settle(dialog, lambda: fake.closed)
    assert fake.closed and dialog.step == dialog.STEP_PHONE
    assert "۳" in error_text({"code": "flood", "seconds": 130})
    dialog.close()


class _Pipe:
    def __init__(self, lines=b""):
        import io

        self.buffer = io.BytesIO(lines)
        self.written = b""

    def readline(self):
        return self.buffer.readline()

    def write(self, data):
        self.written += data

    def flush(self):
        pass


class _Process:
    def __init__(self, answers: list[dict]):
        self.stdout = _Pipe("".join(json.dumps(a) + "\n" for a in answers).encode())
        self.stdin = _Pipe()
        self.killed = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


def test_login_process_talks_json_lines_and_never_uses_the_command_line(monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(setup, "server_command", lambda: ["ShopSystem.exe"])
    started = {}
    process = _Process([{"event": "ready"}, {"event": "connected"}, {"event": "code_sent"}])

    def popen(command, **kwargs):
        started["command"] = command
        return process
    login = setup.TelegramLogin(popen=popen)
    assert login.open() == {"event": "ready"}
    events = login.send({"cmd": "start", "phone": "+989121234567"})
    assert [e["event"] for e in events] == ["connected", "code_sent"]
    assert started["command"] == ["ShopSystem.exe", "--data-dir", str(tmp_path), "--tg-login"]
    assert "989121234567" not in " ".join(started["command"])
    assert b"989121234567" in process.stdin.written
    login.close()
    assert b'"cancel"' in process.stdin.written


def test_session_file_is_detected(monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "data_dir", lambda: tmp_path)
    assert not setup.telegram_logged_in()
    (tmp_path / "shoptg").mkdir()
    (tmp_path / "shoptg" / "tg_session.dpapi").write_bytes(b"x")
    assert setup.telegram_logged_in()


ENV = """DB_SERVER=.\\SQLEXPRESS
DB_NAME=hesab5 t
TG_READER_ENABLED=true
TG_API_PRESET=custom
TG_API_ID=123456
TG_API_HASH=abcdefabcdefabcdefabcdefabcdefab
TG_PRICE_CHANNEL=Some_Channel
TG_PROXY=tg://proxy?server=a&port=1&secret=dd00
"""


def test_settings_wizard_telegram_page(admin_qapp, monkeypatch, tmp_path):
    folder = tmp_path / "ShopServer"
    folder.mkdir()
    (folder / ".env").write_text(ENV, encoding="utf-8")
    monkeypatch.setattr(setup, "data_dir", lambda: folder)
    monkeypatch.setattr(setup, "is_admin", lambda: True)
    monkeypatch.setattr(setup, "odbc_driver_installed", lambda driver=None: True)
    monkeypatch.setattr(setup, "network_is_public", lambda: False)
    from app.ui import server_setup_wizard as wiz

    wizard = wiz.ServerSetupWizard(mode=wiz.MODE_SETTINGS)
    try:
        assert "telegram" in wizard._steps
        assert wizard.tg_enabled.isChecked() and wizard.tg_key_own.isChecked()
        assert wizard.tg_channel.text() == "Some_Channel"
        assert wizard.tg_proxy.text() == "" and wizard.tg_proxy.placeholderText() == wiz.KEEP_SECRET
        assert wizard.tg_proxy.echoMode() == wizard.tg_proxy.EchoMode.Password
        assert not wizard.tg_key_warning.isVisibleTo(wizard)
        extra = wizard.config_extra()
        assert extra["tg_reader_enabled"] is True and extra["tg_api_preset"] == "custom"
        assert extra["tg_proxy"] is None and extra["tg_api_hash"] is None   # kept as saved
        assert wizard.telegram_problem() == ""
        wizard.tg_key_desktop.setChecked(True)
        assert wizard.config_extra()["tg_api_preset"] == "tdesktop"
        assert not wizard.tg_api_id.isEnabled()
        wizard.tg_channel.setText("bad channel!")
        assert "نام کانال" in wizard.telegram_problem()
        wizard.tg_channel.setText("@AbrishamiiPhoneMashhad")
        assert wizard.config_extra()["tg_price_channel"] == "AbrishamiiPhoneMashhad"
        wizard.tg_proxy.setText("http://not-a-proxy")
        assert "پراکسی" in wizard.telegram_problem()
        assert "هنوز وارد" in wizard.tg_login_status.text()
    finally:
        wizard.close()


def test_launcher_knows_the_reader_settings():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "shopsystem" / "launcher.py").read_text(
        encoding="utf-8")
    for field, key in (("tg_reader_enabled", "TG_READER_ENABLED"),
                       ("tg_api_preset", "TG_API_PRESET"), ("tg_price_channel", "TG_PRICE_CHANNEL"),
                       ("tg_proxy", "TG_PROXY")):
        assert f'"{field}": "{key}"' in text


def test_client_build_leaves_the_login_dialog_out():
    from build_shopadmin import SERVER_ONLY_MODULES

    assert "app.ui.telegram_login" in SERVER_ONLY_MODULES
