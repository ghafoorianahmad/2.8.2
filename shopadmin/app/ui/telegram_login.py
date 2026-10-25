"""v2.9.0: «ورود به حساب تلگرام» - the shop's Telegram reader account (server only).

Phone -> the code Telegram sends -> the two-step password (when the account has
one). The answers go straight to ``ShopSystem.exe --tg-login`` through its pipes
(:class:`server_setup.TelegramLogin`); nothing is stored or logged here and the
fields are cleared after each step. The session is saved encrypted on this
server by the server program.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLineEdit, QStackedWidget, QVBoxLayout, QWidget

from .. import server_setup as setup
from ..persian import to_english_digits, to_persian_digits
from . import theme, widgets
from .async_utils import run_async
from .rtl import RIGHT, mark_ltr

ERRORS_FA = {
    "no_connection": "به تلگرام وصل نشد. یک پراکسی سالم در خانهٔ «پراکسی» بنویسید یا در "
                     "«سرور فروشگاه» پراکسی دستی اضافه کنید و دوباره بزنید.",
    "phone_invalid": "شمارهٔ تلفن درست نیست؛ با کد کشور بنویسید، مثلاً ‎+989121234567‎.",
    "phone_banned": "تلگرام این شماره را مسدود کرده است.",
    "api_invalid": "کلید برنامهٔ تلگرام (api_id / api_hash) پذیرفته نشد.",
    "api_missing": "برای «کلید خودم» شناسه و کلید برنامهٔ تلگرام را وارد کنید.",
    "code_expired": "کد منقضی شد؛ دوباره «ارسال کد» را بزنید.",
    "not_registered": "این شماره حساب تلگرام ندارد.",
    "save_failed": "ورود انجام شد ولی ذخیرهٔ امن آن ممکن نشد (این پنجره باید با دسترسی "
                   "«مدیر ویندوز» باز شده باشد).",
}
GENERIC_FA = "کار انجام نشد؛ دوباره امتحان کنید."


def error_text(event: dict) -> str:
    code = str(event.get("code") or "")
    if code == "flood":
        seconds = int(event.get("seconds") or 0)
        minutes = max(1, (seconds + 59) // 60)
        return f"تلگرام گفته {to_persian_digits(minutes)} دقیقه صبر کنید و بعد دوباره امتحان کنید."
    if code == "code_invalid":
        left = int(event.get("left") or 0)
        return (f"کد درست نیست. {to_persian_digits(left)} بار دیگر می‌توانید امتحان کنید."
                if left > 0 else "کد چند بار اشتباه وارد شد؛ دوباره «ارسال کد» را بزنید.")
    if code == "password_invalid":
        left = int(event.get("left") or 0)
        return (f"گذرواژهٔ دومرحله‌ای درست نیست. {to_persian_digits(left)} بار دیگر."
                if left > 0 else "گذرواژه چند بار اشتباه بود؛ از اول وارد شوید.")
    return ERRORS_FA.get(code, GENERIC_FA)


def _field(placeholder: str, *, password: bool = False) -> QLineEdit:
    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    field.setMinimumHeight(38)
    mark_ltr(field)
    field.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    if password:
        field.setEchoMode(QLineEdit.EchoMode.Password)
    return field


class TelegramLoginDialog(widgets.ResponsiveDialog):
    """Three small steps; ``logged_in`` is True after a successful login."""

    STEP_PHONE, STEP_CODE, STEP_PASSWORD, STEP_DONE = range(4)

    def __init__(self, parent: QWidget | None = None, *, preset: str = "tdesktop",
                 api_id: str = "", api_hash: str = "", proxy: str = "",
                 login_factory=setup.TelegramLogin) -> None:
        super().__init__(parent)
        self.setWindowTitle("ورود به حساب تلگرام")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(520)
        self.logged_in = False
        self._key = {"preset": preset, "api_id": api_id, "api_hash": api_hash}
        self._login_factory = login_factory
        self._login: setup.TelegramLogin | None = None
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(widgets.label("ورود به حساب تلگرامِ خوانندهٔ لیست قیمت", size=14, bold=True))
        root.addWidget(widgets.label(
            "فقط یک حساب جداگانه (دوم) به کار ببرید. این حساب فقط کانال‌های عمومی را می‌خواند؛ "
            "پیامی نمی‌فرستد و عضو جایی نمی‌شود. شماره، کد و گذرواژه در هیچ‌جا ذخیره نمی‌شوند؛ "
            "فقط ورود (نشست) به‌صورت رمزشده روی همین سرور می‌ماند.", name="Muted", wrap=True))

        self.stack = QStackedWidget()
        self.phone = _field("+989121234567")
        self.proxy = _field("tg://proxy?server=…  (اختیاری)", password=True)
        self.proxy.setText(proxy)
        self.code = _field("کدی که تلگرام فرستاد")
        self.password = _field("گذرواژهٔ تأیید دومرحله‌ای", password=True)
        for fields, hint in (
            ((("شمارهٔ تلفن حساب:", self.phone), ("پراکسی (اختیاری):", self.proxy)),
             "کد ورود در خود برنامهٔ تلگرامِ همان حساب (یا پیامک) می‌آید."),
            ((("کد ورود:", self.code),),
             "کد را از پیام «Telegram» در برنامهٔ تلگرامِ همان حساب بخوانید."),
            ((("گذرواژهٔ دومرحله‌ای:", self.password),),
             "این حساب «تأیید دومرحله‌ای» دارد؛ گذرواژهٔ آن را وارد کنید."),
        ):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            form = QFormLayout()
            form.setLabelAlignment(RIGHT)
            form.setHorizontalSpacing(14)
            for caption, field in fields:
                form.addRow(widgets.label(caption), field)
            layout.addLayout(form)
            layout.addWidget(widgets.label(hint, name="Muted", wrap=True))
            self.stack.addWidget(page)
        done = QWidget()
        done_layout = QVBoxLayout(done)
        done_layout.setContentsMargins(0, 0, 0, 0)
        done_layout.addWidget(widgets.label(
            "ورود انجام شد و به‌صورت رمزشده روی این سرور ذخیره شد. خوانندهٔ تلگرام چند ثانیه "
            "بعد خودش وصل می‌شود.", color=theme.SUCCESS_DARK, bold=True, wrap=True))
        self.stack.addWidget(done)
        root.addWidget(self.stack)

        self.status = widgets.label("", wrap=True)
        root.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.next_button = widgets.button("ارسال کد", variant="primary", icon_name="check",
                                          on_click=self.next_step)
        self.next_button.setProperty("big", True)
        buttons.addWidget(self.next_button)
        self.close_button = widgets.button("انصراف", on_click=self.reject)
        self.close_button.setProperty("big", True)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)
        self.phone.returnPressed.connect(self.next_step)
        self.code.returnPressed.connect(self.next_step)
        self.password.returnPressed.connect(self.next_step)

    # ------------------------------------------------------------------ steps
    @property
    def step(self) -> int:
        return self.stack.currentIndex()

    def _say(self, text: str, ok: bool | None = None) -> None:
        color = theme.SUCCESS_DARK if ok else (theme.DANGER if ok is False else theme.TEXT_MUTED)
        self.status.setStyleSheet(f"color: {color};")
        self.status.setText(text)

    def _go(self, step: int) -> None:
        self.stack.setCurrentIndex(step)
        self.next_button.setText({self.STEP_PHONE: "ارسال کد", self.STEP_CODE: "تأیید کد",
                                  self.STEP_PASSWORD: "تأیید گذرواژه",
                                  self.STEP_DONE: "بستن"}[step])
        self.close_button.setVisible(step != self.STEP_DONE)
        (self.phone, self.code, self.password, self.next_button)[step].setFocus()

    def next_step(self) -> None:
        if self._busy:
            return
        step = self.step
        if step == self.STEP_DONE:
            self.accept()
            return
        if step == self.STEP_PHONE:
            phone = to_english_digits(self.phone.text()).replace(" ", "").replace("-", "")
            if phone.startswith("00"):
                phone = "+" + phone[2:]
            elif phone.startswith("09"):
                phone = "+98" + phone[1:]
            if len(phone.lstrip("+")) < 10:
                self._say(ERRORS_FA["phone_invalid"], False)
                return
            payload = {"cmd": "start", "phone": phone, "proxy": self.proxy.text().strip(),
                       **self._key}
            self._say("در حال اتصال به تلگرام و درخواست کد… (ممکن است تا یک دقیقه طول بکشد)")
        elif step == self.STEP_CODE:
            code = "".join(ch for ch in to_english_digits(self.code.text()) if ch.isdigit())
            if len(code) < 4:
                self._say("کد ورود را کامل وارد کنید.", False)
                return
            payload = {"cmd": "code", "code": code}
            self._say("در حال بررسی کد…")
        else:
            if not self.password.text():
                self._say("گذرواژه را وارد کنید.", False)
                return
            payload = {"cmd": "password", "password": self.password.text()}
            self._say("در حال بررسی گذرواژه…")
        self._send(payload)

    def _send(self, payload: dict) -> None:
        self._busy = True
        self.next_button.setEnabled(False)

        def work() -> list[dict]:
            if self._login is None:
                self._login = self._login_factory()
                self._login.open()
            return self._login.send(payload)

        run_async(work, on_success=self._answer, on_error=self._failed)
        # what was typed is not kept in the dialog after it was sent
        self.code.clear()
        self.password.clear()

    def _answer(self, events: list[dict]) -> None:
        self._busy = False
        self.next_button.setEnabled(True)
        last = events[-1] if events else {}
        kind = last.get("event")
        if kind == "code_sent":
            self._say("کد فرستاده شد.", True)
            self._go(self.STEP_CODE)
        elif kind == "password_needed":
            self._say("")
            self._go(self.STEP_PASSWORD)
        elif kind == "done":
            self.logged_in = True
            self._say("")
            self._go(self.STEP_DONE)
            self._close_login()
        else:
            self._say(error_text(last), False)
            if not last.get("retry"):
                # start over from the phone number with a new process
                self._close_login()
                self._go(self.STEP_PHONE)

    def _failed(self, message: str, _kind: str) -> None:
        self._busy = False
        self.next_button.setEnabled(True)
        self._close_login()
        self._go(self.STEP_PHONE)
        self._say(message or GENERIC_FA, False)

    def _close_login(self) -> None:
        login, self._login = self._login, None
        if login is not None:
            run_async(login.close)

    def done(self, result: int) -> None:  # noqa: D401 - Qt naming
        self._close_login()
        super().done(result)
