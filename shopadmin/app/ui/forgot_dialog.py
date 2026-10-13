"""پنجرهٔ «فراموشی گذرواژه» (نسخهٔ کلاینت).

۱. نام کاربری → «ارسال درخواست به مدیر»
۲. انتظار تأیید مدیر (هر چند ثانیه وضعیت از سرور پرسیده می‌شود)
۳. پس از تأیید: گذرواژهٔ جدید دلخواه (گذرواژهٔ قبلی همان لحظه بی‌اعتبار می‌شود)

گذرواژه‌ای نمایش یا نگه‌داری نمی‌شود؛ رمز درخواست فقط در حافظهٔ همین پنجره می‌ماند.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ..auth import MIN_PASSWORD_LENGTH, AuthService
from ..persian import to_persian_digits
from . import theme, widgets
from .async_utils import run_async

POLL_MS = 5000
PAGE_ASK, PAGE_WAIT, PAGE_NEW, PAGE_END = range(4)


class ForgotPasswordDialog(QDialog):
    def __init__(self, auth: AuthService, username: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.auth = auth
        self.username = username.strip()
        self.completed = False
        self._request: dict | None = None
        self._busy = False

        self.setWindowTitle("فراموشی گذرواژه")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(widgets.label("فراموشی گذرواژه", size=14, bold=True))
        self.stack = QStackedLayout()
        root.addLayout(self.stack)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        # -- 1. ask
        ask = QWidget()
        lay = QVBoxLayout(ask)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(widgets.label(
            "نام کاربری خود را وارد کنید. درخواست شما برای مدیر فروشگاه فرستاده می‌شود؛ "
            "پس از تأیید او می‌توانید گذرواژهٔ جدید بگذارید.", name="Muted", wrap=True))
        self.username_input = QLineEdit(self.username)
        self.username_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.username_input.setPlaceholderText("نام کاربری")
        self.username_input.setMinimumHeight(40)
        self.username_input.returnPressed.connect(self._send_request)
        lay.addWidget(self.username_input)
        self.send_button = widgets.button("ارسال درخواست به مدیر", variant="primary",
                                          on_click=self._send_request)
        lay.addWidget(self.send_button)
        self.stack.addWidget(ask)

        # -- 2. wait
        wait = QWidget()
        lay = QVBoxLayout(wait)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.wait_label = widgets.label(
            "درخواست شما فرستاده شد و منتظر تأیید مدیر است. این پنجره را باز بگذارید؛ "
            "به‌محض تأیید ادامه می‌دهید.", wrap=True)
        lay.addWidget(self.wait_label)
        lay.addWidget(widgets.button("بررسی وضعیت", on_click=self._poll))
        self.stack.addWidget(wait)

        # -- 3. choose
        new = QWidget()
        lay = QVBoxLayout(new)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(widgets.label(
            "درخواست شما تأیید شد. گذرواژهٔ جدید دلخواه خود را بنویسید.", wrap=True))
        self.password_input = _password_edit(
            f"گذرواژهٔ جدید (حداقل {to_persian_digits(MIN_PASSWORD_LENGTH)} نویسه، حرف و عدد)")
        self.confirm_input = _password_edit("تکرار گذرواژهٔ جدید")
        self.confirm_input.returnPressed.connect(self._complete)
        lay.addWidget(self.password_input)
        lay.addWidget(self.confirm_input)
        self.save_button = widgets.button("تعیین گذرواژهٔ جدید", variant="primary",
                                          on_click=self._complete)
        lay.addWidget(self.save_button)
        self.stack.addWidget(new)

        # -- 4. end
        end = QWidget()
        lay = QVBoxLayout(end)
        lay.setContentsMargins(0, 0, 0, 0)
        self.end_label = widgets.label("", wrap=True)
        lay.addWidget(self.end_label)
        self.again_button = widgets.button("درخواست دوباره", on_click=self._restart)
        lay.addWidget(self.again_button)
        self.stack.addWidget(end)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_button = widgets.button("بستن", on_click=self.reject)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self.finished.connect(lambda _r: self._timer.stop())

    # ------------------------------------------------------------------ helpers
    def _fail(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _show(self, page: int) -> None:
        self.error_label.setVisible(False)
        self.stack.setCurrentIndex(page)

    def _restart(self) -> None:
        self._request = None
        self._show(PAGE_ASK)

    # ------------------------------------------------------------------ steps
    def _send_request(self) -> None:
        if self._busy:
            return
        name = self.username_input.text().strip()
        self.error_label.setVisible(False)
        self._busy = True
        self.send_button.setEnabled(False)

        def ok(result) -> None:
            self.username = name
            self._request = {"request_id": int(result["request_id"]), "token": str(result["token"])}
            self._show(PAGE_WAIT)
            self._timer.start()

        def done() -> None:
            self._busy = False
            self.send_button.setEnabled(True)

        run_async(lambda: self.auth.request_password_reset(name), on_success=ok,
                  on_error=lambda m, _k: self._fail(m), on_done=done)

    def _poll(self) -> None:
        if self._busy or self._request is None:
            return
        request = self._request
        self._busy = True

        def ok(state: str) -> None:
            if state == "approved":
                self._timer.stop()
                self._show(PAGE_NEW)
                self.password_input.setFocus()
            elif state in ("rejected", "expired", "used"):
                self._timer.stop()
                self.end_label.setText(
                    "مدیر درخواست شما را رد کرد." if state == "rejected"
                    else "این درخواست منقضی شده است؛ در صورت نیاز دوباره درخواست دهید.")
                self._show(PAGE_END)

        def done() -> None:
            self._busy = False

        run_async(lambda: self.auth.password_request_status(request["request_id"],
                                                            request["token"]),
                  on_success=ok, on_error=lambda m, _k: self._fail(m), on_done=done)

    def _complete(self) -> None:
        if self._busy or self._request is None:
            return
        request = self._request
        password, confirm = self.password_input.text(), self.confirm_input.text()
        self.error_label.setVisible(False)
        self._busy = True
        self.save_button.setEnabled(False)

        def ok(_r) -> None:
            self.completed = True
            self.password_input.clear()
            self.confirm_input.clear()
            self.accept()

        def done() -> None:
            self._busy = False
            self.save_button.setEnabled(True)

        run_async(lambda: self.auth.complete_password_reset(
            request["request_id"], request["token"], password, confirm),
            on_success=ok, on_error=lambda m, _k: self._fail(m), on_done=done)


def _password_edit(placeholder: str) -> QLineEdit:
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    edit.setPlaceholderText(placeholder)
    edit.setMinimumHeight(40)
    return edit
