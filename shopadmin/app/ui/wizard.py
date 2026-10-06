"""تنظیمات اولیه — ویزارد نخستین اجرا.

سه گام: خوش‌آمد، اتصال به shopapi، و ساخت نخستین «مدیر کل».
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..api_client import ShopApiClient, SystemInfo
from ..auth import AuthError, AuthService, validate_password_strength
from ..logging_setup import get_logger
from ..paths import APP_VERSION, data_dir, db_path
from ..persian import to_persian_digits
from ..store import Store
from . import theme, widgets
from .async_utils import run_async

log = get_logger("wizard")

STEP_TITLES = ("خوش آمدید", "اتصال به سرور فروشگاه", "ساخت مدیر کل")


class SetupWizard(QWidget):
    """First-run configuration. Emits :attr:`finished` when setup completes."""

    finished = Signal()

    def __init__(self, store: Store, auth: AuthService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.auth = auth
        self.toasts = widgets.ToastHost(self)
        self.setWindowTitle("تنظیمات اولیهٔ مدیریت فروشگاه")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(720, 620)
        self.setStyleSheet(f"background: {theme.BACKGROUND};")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        # ---- header ------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(theme.icon_pixmap("settings", 32, theme.PRIMARY))
        logo.setFixedSize(58, 58)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"background: {theme.PRIMARY_SOFT}; border-radius: 16px;")
        header.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(widgets.label("تنظیمات اولیهٔ مدیریت فروشگاه", size=15, bold=True))
        titles.addWidget(widgets.label(
            "این تنظیمات فقط یک‌بار لازم است و سپس ذخیره می‌شود.", name="Muted"
        ))
        header.addLayout(titles, 1)
        root.addLayout(header)

        # ---- step indicator ---------------------------------------------
        self.steps_row = QHBoxLayout()
        self.steps_row.setSpacing(8)
        self._step_labels: list[QLabel] = []
        for index, title in enumerate(STEP_TITLES, start=1):
            chip = widgets.label(f"{to_persian_digits(index)}. {title}")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setMinimumHeight(34)
            chip.setContentsMargins(12, 6, 12, 6)
            self.steps_row.addWidget(chip, 1)
            self._step_labels.append(chip)
        root.addLayout(self.steps_row)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_welcome_step())
        self.stack.addWidget(self._build_connection_step())
        self.stack.addWidget(self._build_admin_step())
        root.addWidget(self.stack, 1)

        # ---- navigation --------------------------------------------------
        nav = QHBoxLayout()
        nav.setSpacing(10)
        nav.addStretch(1)
        self.back_button = widgets.button("مرحلهٔ قبل", on_click=self._back)
        self.next_button = widgets.button(
            "ادامه", variant="primary", icon_name="check", on_click=self._next
        )
        nav.addWidget(self.next_button)
        nav.addWidget(self.back_button)
        root.addLayout(nav)

        self._step = 0
        self._update_step()

    # ------------------------------------------------------------------ steps
    def _build_welcome_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        panel = widgets.Panel()
        panel.body.addWidget(widgets.label(
            "به برنامهٔ مدیریت فروشگاه خوش آمدید.", size=13, bold=True
        ))
        panel.body.addWidget(widgets.label(
            "این برنامهٔ دسکتاپ برای مدیر و کارکنان فروشگاه است و از طریق سرویس "
            "«shopapi» به اطلاعات فروشگاه دسترسی پیدا می‌کند. این برنامه هرگز به‌طور "
            "مستقیم به پایگاه‌دادهٔ حسابداری وصل نمی‌شود.",
            wrap=True,
        ))
        panel.body.addWidget(widgets.hline())
        for text in (
            "آدرس سرور فروشگاه را وارد می‌کنید.",
            "کلید مدیریت (ADMIN_API_KEY) را وارد می‌کنید.",
            "نخستین کاربر «مدیر کل» را برای خودتان می‌سازید.",
        ):
            row = QHBoxLayout()
            icon = QLabel()
            icon.setPixmap(theme.icon_pixmap("check", 18, theme.SUCCESS))
            row.addWidget(icon)
            row.addWidget(widgets.label(text, wrap=True), 1)
            panel.body.addLayout(row)

        panel.body.addWidget(widgets.hline())
        panel.body.addWidget(widgets.label(
            f"پروندهٔ تنظیمات محلی: {db_path()}", name="Faint", wrap=True
        ))
        panel.body.addWidget(widgets.label(
            f"نسخهٔ برنامه: {to_persian_digits(APP_VERSION)}", name="Faint"
        ))
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _build_connection_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        panel = widgets.Panel("گام ۲ — اتصال به سرور فروشگاه")
        panel.body.addWidget(widgets.label(
            "این اطلاعات را از فایل .env سرویس shopapi بردارید.", name="Muted", wrap=True
        ))

        panel.body.addWidget(widgets.label("آدرس سرور فروشگاه"))
        self.base_url_input = QLineEdit(
            self.store.get_setting("shopapi_base_url", "http://127.0.0.1:8000")
        )
        self.base_url_input.setPlaceholderText("http://127.0.0.1:8000")
        self.base_url_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.base_url_input.setMinimumHeight(42)
        panel.body.addWidget(self.base_url_input)

        panel.body.addWidget(widgets.label("کلید مدیریت (ADMIN_API_KEY)"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("کلید مدیریت را وارد کنید")
        self.api_key_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.api_key_input.setMinimumHeight(42)
        panel.body.addWidget(self.api_key_input)

        test_row = QHBoxLayout()
        self.test_button = widgets.button(
            "آزمایش اتصال", icon_name="wifi", variant="primary", on_click=self._test_connection
        )
        test_row.addWidget(self.test_button)
        test_row.addStretch(1)
        panel.body.addLayout(test_row)

        self.connection_result = widgets.label("", wrap=True)
        self.connection_result.setVisible(False)
        panel.body.addWidget(self.connection_result)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _build_admin_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        panel = widgets.Panel("گام ۳ — ساخت نخستین کاربر «مدیر کل»")
        panel.body.addWidget(widgets.label(
            "این کاربر، مدیر فروشگاه است و می‌تواند بعداً کاربران دیگر کارکنان را بسازد. "
            "این کاربران فقط به همین برنامه دسترسی دارند و با مشتریان فروشگاه تفاوت دارند.",
            name="Muted", wrap=True,
        ))

        panel.body.addWidget(widgets.label("نام و نام خانوادگی"))
        self.full_name_input = QLineEdit()
        self.full_name_input.setPlaceholderText("مثلاً: علی رضایی")
        self.full_name_input.setMinimumHeight(42)
        panel.body.addWidget(self.full_name_input)

        panel.body.addWidget(widgets.label("نام کاربری (انگلیسی، بدون فاصله)"))
        self.new_username_input = QLineEdit()
        self.new_username_input.setPlaceholderText("مثلاً: owner")
        self.new_username_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.new_username_input.setMinimumHeight(42)
        panel.body.addWidget(self.new_username_input)

        panel.body.addWidget(widgets.label("گذرواژه (حداقل ۶ نویسه)"))
        self.new_password_input = QLineEdit()
        self.new_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_password_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.new_password_input.setMinimumHeight(42)
        panel.body.addWidget(self.new_password_input)

        panel.body.addWidget(widgets.label("تکرار گذرواژه"))
        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.confirm_password_input.setMinimumHeight(42)
        panel.body.addWidget(self.confirm_password_input)

        self.admin_error = widgets.label("", color=theme.DANGER, wrap=True)
        self.admin_error.setVisible(False)
        panel.body.addWidget(self.admin_error)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ nav
    def _update_step(self) -> None:
        self.stack.setCurrentIndex(self._step)
        self.back_button.setEnabled(self._step > 0)
        self.next_button.setText(
            "پایان و ورود" if self._step == len(STEP_TITLES) - 1 else "ادامه"
        )
        for index, chip in enumerate(self._step_labels):
            if index == self._step:
                chip.setStyleSheet(
                    f"background: {theme.PRIMARY}; color: #FFFFFF; border-radius: 10px; "
                    f"font-weight: 700;"
                )
            elif index < self._step:
                chip.setStyleSheet(
                    f"background: {theme.SUCCESS_LIGHT}; color: {theme.SUCCESS_DARK}; "
                    f"border-radius: 10px; font-weight: 600;"
                )
            else:
                chip.setStyleSheet(
                    f"background: {theme.SURFACE}; color: {theme.TEXT_MUTED}; "
                    f"border: 1px solid {theme.BORDER}; border-radius: 10px;"
                )

    def _back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._update_step()

    def _next(self) -> None:
        if self._step == 0:
            self._step = 1
            self._update_step()
            self.base_url_input.setFocus()
            return
        if self._step == 1:
            if not self._valid_base_url():
                return
            # Saving requires a key; a wrong key is caught by the real test.
            self.store.configure_connection(
                self.base_url_input.text().strip(), self.api_key_input.text().strip()
            )
            self._step = 2
            self._update_step()
            self.full_name_input.setFocus()
            return
        self._finish()

    def _valid_base_url(self) -> bool:
        url = self.base_url_input.text().strip()
        if not url.startswith(("http://", "https://")):
            self._show_connection_result(
                "آدرس سرور باید با http:// یا https:// شروع شود.", ok=False
            )
            return False
        if not self.api_key_input.text().strip():
            self._show_connection_result("کلید مدیریت (ADMIN_API_KEY) را وارد کنید.", ok=False)
            return False
        return True

    # ------------------------------------------------------------------ test
    def _show_connection_result(self, message: str, *, ok: bool, detail: str = "") -> None:
        self.connection_result.setText(message + (f"\n{detail}" if detail else ""))
        self.connection_result.setStyleSheet(
            f"color: {theme.SUCCESS_DARK if ok else theme.DANGER};"
        )
        self.connection_result.setVisible(True)

    def _test_connection(self) -> None:
        if not self._valid_base_url():
            return
        base_url = self.base_url_input.text().strip()
        api_key = self.api_key_input.text().strip()
        self.test_button.setEnabled(False)
        self.test_button.setText("در حال آزمایش…")
        self._show_connection_result("در حال برقراری ارتباط با سرور فروشگاه…", ok=True)

        probe = ShopApiClient(base_url, api_key, timeout=10)

        def work() -> SystemInfo:
            try:
                return probe.test_connection()
            finally:
                probe.close()

        def ok(info: SystemInfo) -> None:
            detail = (
                "ثبت در حسابداری فعال است."
                if info.accounting_write_enabled
                else "هشدار: حالت آزمایشی فعال است؛ سفارش‌ها در حسابداری ثبت نمی‌شوند."
            )
            self._show_connection_result(
                "ارتباط با موفقیت برقرار شد. کلید مدیریت معتبر است.", ok=True, detail=detail
            )

        def fail(message: str, _kind: str) -> None:
            self._show_connection_result(message, ok=False)

        def done() -> None:
            self.test_button.setEnabled(True)
            self.test_button.setText("آزمایش اتصال")

        run_async(work, on_success=ok, on_error=fail, on_done=done)

    # ------------------------------------------------------------------ finish
    def _finish(self) -> None:
        full_name = self.full_name_input.text().strip()
        username = self.new_username_input.text().strip()
        password = self.new_password_input.text()

        if not full_name:
            self._admin_error("نام و نام خانوادگی را وارد کنید.")
            return
        if not username:
            self._admin_error("نام کاربری را وارد کنید.")
            return
        if password != self.confirm_password_input.text():
            self._admin_error("تکرار گذرواژه با گذرواژهٔ یکسان نیست.")
            return
        problem = validate_password_strength(password)
        if problem:
            self._admin_error(problem)
            return

        self.store.configure_connection(
            self.base_url_input.text().strip(), self.api_key_input.text().strip()
        )
        try:
            principal = self.auth.create_first_super_admin(username, full_name, password)
        except AuthError as exc:
            self._admin_error(exc.message)
            return

        self.store.set_setting("wizard_completed", True)
        self.store.audit(principal.username, "setup", "تنظیمات اولیهٔ برنامه انجام شد")
        log.info("first-run wizard completed for admin user id=%s", principal.user_id)
        self.finished.emit()

    def _admin_error(self, message: str) -> None:
        self.admin_error.setText(message)
        self.admin_error.setVisible(True)


def needs_setup(store: Store, auth: AuthService) -> bool:
    """True when the wizard must run: no connection config or no admin user."""
    return not store.is_configured() or auth.needs_first_super_admin
