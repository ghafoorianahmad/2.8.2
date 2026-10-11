"""راه‌اندازی سرور فروشگاه — فقط روی رایانهٔ سرور و با دسترسی مدیر ویندوز.

گام‌ها: بررسی پیش‌نیازها، پایگاه‌دادهٔ حسابداری، شبکه، ربات‌ها (اختیاری)،
نخستین مدیر کل، و اجرای خودکار همهٔ کارها با نمایش پیشرفت.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import server_setup as setup
from ..api_client import ShopApiClient, short_fingerprint
from ..auth import MIN_PASSWORD_LENGTH, USERNAME_RE, validate_password_strength
from ..logging_setup import get_logger
from ..persian import to_english_digits, to_persian_digits
from . import theme, widgets
from .async_utils import run_async

log = get_logger("server_setup_ui")

STEPS = ("پیش‌نیازها", "حسابداری", "شبکه", "ربات‌ها", "مدیر کل", "اجرا")


def _line(placeholder: str = "", *, ltr: bool = True, password: bool = False) -> QLineEdit:
    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    field.setMinimumHeight(38)
    if ltr:
        field.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    if password:
        field.setEchoMode(QLineEdit.EchoMode.Password)
    return field


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(12)
    return form


class ServerSetupWizard(QWidget):
    """Emits :attr:`completed` with (base_url, certificate_pem) when the server runs."""

    completed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("راه‌اندازی سرور فروشگاه")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(780, 660)
        # Scoped to this window only: an unscoped "background" would also paint
        # every child, overriding the white-on-blue primary buttons.
        self.setObjectName("WindowRoot")
        self.setStyleSheet(f"QWidget#WindowRoot {{ background: {theme.BACKGROUND}; }}")
        self.toasts = widgets.ToastHost(self)
        self._db_ok = False
        self._result: tuple[str, str] | None = None
        self._needs_admin = True

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(16)
        root.addWidget(widgets.label("راه‌اندازی سرور فروشگاه", size=15, bold=True))
        root.addWidget(widgets.label(
            "این کار فقط یک‌بار و روی همان رایانه‌ای انجام می‌شود که حسابداری روی آن است.",
            name="Muted"))

        chips = QHBoxLayout()
        self._chips: list[QLabel] = []
        for index, title in enumerate(STEPS, start=1):
            chip = widgets.label(f"{to_persian_digits(index)}. {title}")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setMinimumHeight(32)
            chips.addWidget(chip, 1)
            self._chips.append(chip)
        root.addLayout(chips)

        self.stack = QStackedWidget()
        for builder in (self._page_checks, self._page_database, self._page_network,
                        self._page_bots, self._page_admin, self._page_run):
            self.stack.addWidget(builder())
        root.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        nav.addStretch(1)
        self.back_button = widgets.button("مرحلهٔ قبل", on_click=self._back)
        self.next_button = widgets.button("ادامه", variant="primary", icon_name="check",
                                          on_click=self._next)
        nav.addWidget(self.next_button)
        nav.addWidget(self.back_button)
        root.addLayout(nav)
        self._step = 0
        self._update()
        self._run_checks()

    # ------------------------------------------------------------------ pages
    def _page_checks(self) -> QWidget:
        panel = widgets.Panel("بررسی پیش‌نیازها")
        self.checks_label = widgets.label("در حال بررسی…", wrap=True)
        panel.body.addWidget(self.checks_label)
        panel.body.addWidget(widgets.hline())
        panel.body.addWidget(widgets.label(
            "پس از راه‌اندازی، سرور با روشن شدن ویندوز خودکار اجرا می‌شود، در صورت خطا "
            "دوباره بالا می‌آید و فقط از شبکهٔ محلی فروشگاه قابل دسترسی است. همهٔ ارتباط‌ها "
            "رمزنگاری می‌شوند و کلیدها و تنظیمات فقط در پوشه‌ای ذخیره می‌شوند که تنها "
            "مدیران ویندوز به آن دسترسی دارند.", name="Muted", wrap=True))
        return panel

    def _page_database(self) -> QWidget:
        panel = widgets.Panel("اتصال به پایگاه‌دادهٔ حسابداری (سازه حساب)")
        form = _form()
        self.db_server = _line(r".\SQLEXPRESS")
        self.db_server.setText(r".\SQLEXPRESS")
        self.db_name = _line("نام پایگاه‌داده، مثلاً hesab5")
        form.addRow(widgets.label("نام سرور SQL:"), self.db_server)
        form.addRow(widgets.label("نام پایگاه‌داده:"), self.db_name)
        panel.body.addLayout(form)

        self.auth_sql = QRadioButton("ورود SQL (توصیه می‌شود: کاربر با دسترسی محدود، مثل shopbot)")
        self.auth_windows = QRadioButton("حساب ویندوز همین کاربر (سرور با این حساب اجرا می‌شود)")
        group = QButtonGroup(self)
        group.addButton(self.auth_sql)
        group.addButton(self.auth_windows)
        self.auth_sql.setChecked(True)
        panel.body.addWidget(self.auth_sql)
        sql_form = _form()
        self.db_user = _line("shopbot")
        self.db_password = _line(password=True)
        sql_form.addRow(widgets.label("نام کاربری SQL:"), self.db_user)
        sql_form.addRow(widgets.label("گذرواژهٔ SQL:"), self.db_password)
        panel.body.addLayout(sql_form)
        panel.body.addWidget(self.auth_windows)
        win_form = _form()
        self.win_password = _line(password=True)
        win_form.addRow(widgets.label(f"گذرواژهٔ ویندوز ({setup.current_windows_user()}):"),
                        self.win_password)
        panel.body.addLayout(win_form)
        self.auth_sql.toggled.connect(self._auth_changed)
        self._auth_changed()

        row = QHBoxLayout()
        self.db_test_button = widgets.button("ذخیره و آزمایش اتصال", icon_name="wifi",
                                             variant="primary", on_click=self._test_database)
        row.addWidget(self.db_test_button)
        row.addStretch(1)
        panel.body.addLayout(row)
        self.db_result = widgets.label("", wrap=True)
        panel.body.addWidget(self.db_result)
        return panel

    def _page_network(self) -> QWidget:
        panel = widgets.Panel("شبکه")
        form = _form()
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(setup.existing_config_port() or setup.DEFAULT_PORT)
        self.port.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        form.addRow(widgets.label("درگاه (Port):"), self.port)
        panel.body.addLayout(form)
        addresses = setup.lan_addresses()
        panel.body.addWidget(widgets.label(
            "رایانه‌های کارکنان با این نشانی‌ها به سرور وصل می‌شوند: "
            + ("، ".join(addresses) if addresses else "(نشانی شبکه پیدا نشد)"),
            wrap=True))
        panel.body.addWidget(widgets.label(
            "یک قانون دیوار آتش ویندوز فقط برای شبکهٔ محلی (شبکه‌های خصوصی و دامنه) ساخته "
            "می‌شود. برای ثابت ماندن نشانی، بهتر است برای این رایانه در مودم/روتر یک IP ثابت "
            "تعیین کنید.", name="Muted", wrap=True))
        self.public_warning = widgets.label("", color=theme.DANGER, wrap=True)
        self.public_warning.setVisible(False)
        panel.body.addWidget(self.public_warning)
        return panel

    def _page_bots(self) -> QWidget:
        panel = widgets.Panel("ربات‌ها و پرداخت (اختیاری — بعداً هم از صفحهٔ «سرور فروشگاه» قابل تنظیم است)")
        form = _form()
        self.bank_text = _line("مثلاً: کارت ۶۰۳۷… به نام …", ltr=False)
        self.bale_token = _line("از ربات سازندهٔ بله", password=True)
        self.admin_chats = _line("bale:654321")
        form.addRow(widgets.label("متن حساب بانکی:"), self.bank_text)
        form.addRow(widgets.label("توکن ربات بله:"), self.bale_token)
        form.addRow(widgets.label("گفت‌وگوی مدیران در ربات:"), self.admin_chats)
        panel.body.addLayout(form)
        return panel

    def _page_admin(self) -> QWidget:
        panel = widgets.Panel("نخستین «مدیر کل»")
        self.admin_note = widgets.label(
            "این حساب مدیر فروشگاه است و بعداً حساب کارکنان را می‌سازد.", name="Muted", wrap=True)
        panel.body.addWidget(self.admin_note)
        form = _form()
        self.admin_full_name = _line("مثلاً: علی رضایی", ltr=False)
        self.admin_username = _line("owner")
        self.admin_password = _line(password=True)
        self.admin_confirm = _line(password=True)
        form.addRow(widgets.label("نام و نام خانوادگی:"), self.admin_full_name)
        form.addRow(widgets.label("نام کاربری:"), self.admin_username)
        form.addRow(widgets.label(
            f"گذرواژه (حداقل {to_persian_digits(MIN_PASSWORD_LENGTH)} نویسه، حرف و عدد):"),
            self.admin_password)
        form.addRow(widgets.label("تکرار گذرواژه:"), self.admin_confirm)
        panel.body.addLayout(form)
        self.admin_error = widgets.label("", color=theme.DANGER, wrap=True)
        panel.body.addWidget(self.admin_error)
        return panel

    def _page_run(self) -> QWidget:
        panel = widgets.Panel("راه‌اندازی")
        self.progress = QPlainTextEdit()
        self.progress.setReadOnly(True)
        self.progress.setMinimumHeight(200)
        panel.body.addWidget(self.progress)
        self.final_box = QWidget()
        final = QVBoxLayout(self.final_box)
        final.setContentsMargins(0, 0, 0, 0)
        final.addWidget(widgets.label("سرور آماده است. روی رایانهٔ هر کارمند «مدیریت فروشگاه» را "
                                      "نصب کنید و این نشانی را وارد کنید:", wrap=True))
        self.final_address = widgets.label("", size=13, bold=True)
        self.final_address.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.final_address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        final.addWidget(self.final_address)
        final.addWidget(widgets.label("اثرانگشت امنیتی که باید روی رایانهٔ کارمند همین باشد:",
                                      wrap=True))
        self.final_fingerprint = widgets.label("", size=15, bold=True)
        self.final_fingerprint.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.final_fingerprint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        final.addWidget(self.final_fingerprint)
        self.final_box.setVisible(False)
        panel.body.addWidget(self.final_box)
        return panel

    # ------------------------------------------------------------------ helpers
    def _auth_changed(self) -> None:
        sql = self.auth_sql.isChecked()
        self.db_user.setEnabled(sql)
        self.db_password.setEnabled(sql)
        self.win_password.setEnabled(not sql)
        self._db_ok = False

    def _db_config(self) -> setup.DatabaseConfig:
        return setup.DatabaseConfig(
            server=self.db_server.text().strip(),
            database=self.db_name.text().strip(),
            trusted=self.auth_windows.isChecked(),
            user=self.db_user.text().strip(),
            password=self.db_password.text(),
        )

    def _update(self) -> None:
        self.stack.setCurrentIndex(self._step)
        self.back_button.setEnabled(0 < self._step < len(STEPS) - 1)
        self.next_button.setText("راه‌اندازی" if self._step == len(STEPS) - 2 else
                                 "پایان" if self._step == len(STEPS) - 1 else "ادامه")
        for index, chip in enumerate(self._chips):
            if index == self._step:
                chip.setStyleSheet(f"background: {theme.PRIMARY}; color: #FFFFFF; "
                                   "border-radius: 10px; font-weight: 700;")
            elif index < self._step:
                chip.setStyleSheet(f"background: {theme.SUCCESS_LIGHT}; color: {theme.SUCCESS_DARK}; "
                                   "border-radius: 10px; font-weight: 600;")
            else:
                chip.setStyleSheet(f"background: {theme.SURFACE}; color: {theme.TEXT_MUTED}; "
                                   f"border: 1px solid {theme.BORDER}; border-radius: 10px;")

    def _say(self, text: str, ok: bool | None = None) -> None:
        mark = "✔ " if ok else "✖ " if ok is False else "… "
        self.progress.appendPlainText(mark + text)

    # ------------------------------------------------------------------ checks
    def _run_checks(self) -> None:
        def work() -> dict:
            return {"admin": setup.is_admin(), "odbc": setup.odbc_driver_installed(),
                    "public": setup.network_is_public(),
                    "existing": setup.existing_config_port() is not None}

        def ok(result: dict) -> None:
            lines = []
            lines.append("✔ برنامه با دسترسی مدیر ویندوز اجرا شده است." if result["admin"] else
                         "✖ برنامه باید با دسترسی مدیر ویندوز اجرا شود.")
            lines.append("✔ درایور ODBC Driver 17 for SQL Server نصب است." if result["odbc"] else
                         "✖ درایور «ODBC Driver 17 for SQL Server» نصب نیست. آن را از سایت "
                         "مایکروسافت نصب و دوباره این برنامه را اجرا کنید.")
            if result["existing"]:
                lines.append("ℹ تنظیمات قبلی سرور پیدا شد؛ کلیدهای موجود حفظ می‌شوند.")
            self.checks_label.setText("\n".join(lines))
            self._prereq_ok = result["admin"] and result["odbc"]
            if result["public"]:
                self.public_warning.setText(
                    "هشدار: نوع شبکهٔ این رایانه «عمومی» (Public) است و ویندوز اتصال کارکنان را "
                    "مسدود می‌کند. در تنظیمات ویندوز، شبکه را «خصوصی» (Private) کنید.")
                self.public_warning.setVisible(True)

        self._prereq_ok = False
        run_async(work, on_success=ok)

    # ------------------------------------------------------------------ database
    def _test_database(self) -> None:
        db = self._db_config()
        if not db.server or not db.database:
            self._db_message("نام سرور و نام پایگاه‌داده را وارد کنید.", False)
            return
        if not db.trusted and (not db.user or not db.password):
            self._db_message("نام کاربری و گذرواژهٔ SQL را وارد کنید.", False)
            return
        self.db_test_button.setEnabled(False)
        self._db_message("در حال ذخیره و آزمایش…", None)

        def work() -> dict:
            setup.harden_data_dir(setup.current_windows_user() if db.trusted else None)
            setup.write_config(db, port=self.port.value())
            return setup.check_database()

        def ok(result: dict) -> None:
            self._db_ok = True
            self._db_message(f"اتصال برقرار شد ({to_persian_digits(result.get('groups', 0))} گروه کالا).",
                             True)

        def fail(message: str, _kind: str) -> None:
            self._db_ok = False
            self._db_message(message, False)

        run_async(work, on_success=ok, on_error=fail,
                  on_done=lambda: self.db_test_button.setEnabled(True))

    def _db_message(self, text: str, ok: bool | None) -> None:
        color = theme.SUCCESS_DARK if ok else theme.DANGER if ok is False else theme.TEXT_MUTED
        self.db_result.setText(text)
        self.db_result.setStyleSheet(f"color: {color};")

    # ------------------------------------------------------------------ navigation
    def _back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._update()

    def _next(self) -> None:
        if self._step == 0:
            if not self._prereq_ok:
                widgets.error(self, "پیش‌نیازها", "ابتدا موارد علامت‌خورده با ✖ را برطرف کنید.")
                return
        elif self._step == 1:
            if not self._db_ok:
                widgets.error(self, "حسابداری", "ابتدا «ذخیره و آزمایش اتصال» را با موفقیت انجام دهید.")
                return
            if self.auth_windows.isChecked() and not self.win_password.text():
                widgets.error(self, "حسابداری", "گذرواژهٔ حساب ویندوز را وارد کنید.")
                return
        elif self._step == 4:
            if not self._validate_admin():
                return
            self._step += 1
            self._update()
            self.next_button.setEnabled(False)
            self.back_button.setEnabled(False)
            self._execute()
            return
        elif self._step == 5:
            if self._result:
                self.completed.emit(*self._result)
            self.close()
            return
        self._step += 1
        self._update()

    def _validate_admin(self) -> bool:
        self.admin_error.setText("")
        name = self.admin_full_name.text().strip()
        username = to_english_digits(self.admin_username.text()).strip()
        password = self.admin_password.text()
        if not name:
            self.admin_error.setText("نام و نام خانوادگی را وارد کنید.")
        elif not USERNAME_RE.match(username):
            self.admin_error.setText("نام کاربری باید ۳ تا ۳۲ نویسهٔ انگلیسی، عدد، نقطه یا خط تیره باشد.")
        elif password != self.admin_confirm.text():
            self.admin_error.setText("تکرار گذرواژه یکسان نیست.")
        else:
            problem = validate_password_strength(password)
            if problem:
                self.admin_error.setText(problem)
        return not self.admin_error.text()

    # ------------------------------------------------------------------ execution
    def _execute(self) -> None:
        db = self._db_config()
        port = self.port.value()
        windows_user = setup.current_windows_user() if db.trusted else None
        windows_password = self.win_password.text()
        extra = {
            "bank_account_text": self.bank_text.text().strip(),
            "bale_token": self.bale_token.text().strip(),
            "admin_chat_ids": self.admin_chats.text().strip(),
        }
        admin = (self.admin_username.text().strip(), self.admin_full_name.text().strip(),
                 self.admin_password.text())

        def work(on_progress) -> tuple[str, str, str]:
            on_progress("محدود کردن دسترسی پوشهٔ داده")
            setup.harden_data_dir(windows_user)
            on_progress("نوشتن تنظیمات سرور")
            setup.write_config(db, port=port, extra=extra)
            on_progress("ساخت وظیفهٔ خودکار ویندوز")
            setup.register_task(run_as_user=windows_user, password=windows_password)
            on_progress("باز کردن دیوار آتش برای شبکهٔ محلی")
            setup.open_firewall(port)
            on_progress("روشن کردن سرور")
            setup.start_task()
            on_progress("منتظر آماده شدن سرور (تا ۹۰ ثانیه)")
            pem, fingerprint = setup.wait_until_ready(port)
            base_url = f"https://127.0.0.1:{port}"
            client = ShopApiClient(base_url, server_cert_pem=pem, timeout=15)
            try:
                if client.auth_status().get("bootstrap_required"):
                    on_progress("ساخت مدیر کل")
                    client.bootstrap(setup.service_key(), *admin)
                else:
                    on_progress("مدیر کل از قبل وجود دارد؛ با همان حساب وارد شوید")
            finally:
                client.close()
            return base_url, pem, fingerprint

        def ok(result: tuple[str, str, str]) -> None:
            base_url, pem, fingerprint = result
            self._result = (base_url, pem)
            self._say("سرور فروشگاه آماده است.", True)
            port_text = str(port)
            addresses = setup.lan_addresses() or ["<نشانی این رایانه>"]
            self.final_address.setText("\n".join(f"https://{a}:{port_text}" for a in addresses))
            self.final_fingerprint.setText(short_fingerprint(fingerprint))
            self.final_box.setVisible(True)
            self.next_button.setEnabled(True)
            log.info("server setup finished")

        def fail(message: str, _kind: str) -> None:
            self._say(message, False)
            self.back_button.setEnabled(True)
            self._step = 4
            widgets.error(self, "راه‌اندازی سرور", message)
            self._update()

        run_async(work, on_success=ok, on_error=fail, on_progress=lambda m: self._say(m))
