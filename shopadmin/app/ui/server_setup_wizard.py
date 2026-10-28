"""راه‌اندازی و «تنظیمات سرور» فروشگاه — فقط روی رایانهٔ سرور و با دسترسی مدیر ویندوز.

دو حالت:

* **راه‌اندازی** (``mode="setup"``، پس از نصب): پیش‌نیازها، پایگاه‌دادهٔ حسابداری،
  شبکه، ربات‌ها (اختیاری)، نخستین مدیر کل و اجرای خودکار همهٔ کارها.
* **تنظیمات سرور** (``mode="settings"``، v2.8.1، میان‌بر «تنظیمات سرور» یا صفحهٔ
  «سرور فروشگاه»): همان صفحه‌ها با مقدارهای فعلی؛ رمزها نمایش داده نمی‌شوند و
  خالی گذاشتن آن‌ها یعنی «بدون تغییر». پس از ذخیره سرویس ShopServer دوباره
  راه‌اندازی می‌شود؛ نصب دوباره لازم نیست.

فهرست پایگاه‌داده‌های مجاز و روشن کردن «ثبت واقعی» برای هر پایگاه‌داده فقط همین‌جا
(روی خود رایانهٔ سرور) تغییر می‌کند و هر روشن کردن هشدار و تأیید دارد.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
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
from .rtl import RIGHT, mark_ltr
from ..localshare import is_network_path as setup_is_network

log = get_logger("server_setup_ui")

MODE_SETUP = "setup"
MODE_SETTINGS = "settings"

#: step key -> title. v2.9.4: «مدیر کل» in both modes (blank = the owner stays);
#: «ابزارها» (status-code helper, test-data cleanup) only in «تنظیمات سرور».
STEP_TITLES = {"checks": "پیش‌نیازها", "database": "حسابداری", "network": "شبکه",
               "bots": "ربات‌ها", "telegram": "تلگرام", "admin": "مدیر کل", "tools": "ابزارها",
               "run": "اجرا"}
STEPS = tuple(t for k, t in STEP_TITLES.items() if k != "tools")   # the first setup
CHOOSE_DB = "— پایگاه‌داده را انتخاب کنید —"

KEEP_SECRET = "تنظیم شده — خالی بگذارید تا تغییر نکند"
#: v2.9.0: the public channel the price lists come from
DEFAULT_PRICE_CHANNEL = "AbrishamiiPhoneMashhad"
_CHANNEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_PROXY_RE = re.compile(r"^(tg://(web)?proxy\?|(https?://)?(www\.)?(t|telegram)\.(me|dog)/(web)?proxy/?\?)\S+$",
                       re.I)
#: v2.9.1: role of each joined channel (only the first two are read today)
CHANNEL_ROLES = (("", "انتخاب نشده"), ("pricelist", "لیست قیمت (گوشی)"), ("proxy", "پراکسی"),
                 # v2.14.0: read and kept in «لیست‌های دریافتی»; the basis stays «لیست قیمت»
                 ("price_other", "کانال قیمت دیگر (فقط خواندن)"),
                 ("accessories", "لوازم جانبی (به‌زودی)"), ("used", "گوشی کارکرده (به‌زودی)"),
                 ("ignore", "نادیده"))
CHANNEL_HEADERS = ("کانال", "نشانی", "نقش")
TDESKTOP_WARNING = (
    "این کلیدِ عمومیِ برنامهٔ رسمی Telegram Desktop است و فقط برای شروع است؛ تلگرام ممکن است "
    "حسابی را که با آن از برنامهٔ دیگری وارد می‌شود محدود کند. فقط با یک حساب دوم (جدا از "
    "حساب اصلی فروشگاه) به کار ببرید و هر وقت توانستید «کلید خودم» را از my.telegram.org "
    "بگذارید.")
WRITE_WARNING = (
    "با روشن کردن «ثبت واقعی» برای «{name}»، سفارش‌هایی که در «مدیریت فروشگاه» تأیید "
    "می‌شوند واقعاً در «سازه حساب» (پایگاه‌دادهٔ {name}) ثبت می‌شوند و از این برنامه "
    "حذف‌شدنی نیستند.\n\nفقط وقتی روشن کنید که مطمئنید این پایگاه‌داده همان است که "
    "می‌خواهید سفارش‌ها در آن ثبت شوند (و از آن پشتیبان دارید). ادامه می‌دهید؟")


def _line(placeholder: str = "", *, ltr: bool = True, password: bool = False) -> QLineEdit:
    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    field.setMinimumHeight(38)
    if ltr:
        mark_ltr(field)
    if password:
        field.setEchoMode(QLineEdit.EchoMode.Password)
    return field


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setLabelAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(12)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    return form


def _same_name(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


class DatabasePicker(QComboBox):
    """v2.9.4: the database is CHOSEN from the databases of the SQL Server (no
    free typing: «hesab2» was typed by mistake). ``text()`` / ``setText()`` keep
    the line-edit interface; a saved name that is not on the list is shown
    marked until the list is read."""

    textChanged = Signal(str)
    #: the person picked another database (not a programmatic change)
    textEdited = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditable(False)
        self.setMinimumHeight(38)
        self.setMinimumContentsLength(18)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        mark_ltr(self)
        self._names: list[str] = []
        self.loaded = False
        self.addItem(CHOOSE_DB, "")
        self.currentIndexChanged.connect(lambda _i: self.textChanged.emit(self.text()))
        self.activated.connect(lambda _i: self.textEdited.emit(self.text()))

    def text(self) -> str:
        return str(self.currentData() or "")

    def names(self) -> list[str]:
        return list(self._names)

    def setText(self, name: str) -> None:  # noqa: N802 - line-edit interface
        name = str(name or "").strip()
        if not name:
            self.setCurrentIndex(0)
            return
        index = self.findData(name)
        if index < 0:
            for i in range(1, self.count()):
                if _same_name(str(self.itemData(i) or ""), name):
                    index = i
                    break
        if index < 0:
            self.addItem(name if not self.loaded else f"{name} (روی این سرور پیدا نشد)", name)
            index = self.count() - 1
        self.setCurrentIndex(index)

    def set_names(self, names: list[str]) -> None:
        """The list read from the server; the current choice stays when present."""
        current = self.text()
        self.blockSignals(True)
        self.clear()
        self.addItem(CHOOSE_DB, "")
        self._names = sorted({str(n) for n in names if str(n).strip()}, key=str.lower)
        for name in self._names:
            self.addItem(name, name)
        self.loaded = True
        self.blockSignals(False)
        self.setText(current)
        self.textChanged.emit(self.text())


class DatabaseAccessList(QWidget):
    """فهرست پایگاه‌داده‌های مجاز، هرکدام با تیک «ثبت واقعی» (با هشدار و تأیید)."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, QCheckBox, QWidget]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.grid_holder = QWidget()
        self.grid = QGridLayout(self.grid_holder)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(6)
        layout.addWidget(self.grid_holder)
        self.empty_label = widgets.label(
            "هنوز هیچ پایگاه‌داده‌ای مجاز نشده است: سرور فقط می‌خواند و هیچ سفارشی واقعاً "
            "در حسابداری ثبت نمی‌شود.", name="Muted", wrap=True)
        layout.addWidget(self.empty_label)
        add_row = QHBoxLayout()
        # v2.9.4: chosen from the server's databases, never typed
        self.name_input = DatabasePicker()
        add_row.addWidget(self.name_input, 1)
        add_row.addWidget(widgets.button("افزودن به فهرست مجاز", icon_name="plus",
                                         on_click=self._add_typed))
        layout.addLayout(add_row)
        self._render()

    # ---- data ---------------------------------------------------------------
    def set_values(self, allowed: list[str], writing: list[str]) -> None:
        self._rows.clear()
        for name in allowed:
            self._add(name, any(_same_name(name, w) for w in writing), confirm=False)
        self._render()

    def allowed(self) -> list[str]:
        return [name for name, _check, _row in self._rows]

    def writing(self) -> list[str]:
        return [name for name, check, _row in self._rows if check.isChecked()]

    def contains(self, name: str) -> bool:
        return any(_same_name(name, n) for n in self.allowed())

    def write_on(self, name: str) -> bool:
        return any(_same_name(name, n) for n in self.writing())

    def add(self, name: str) -> bool:
        name = name.strip()
        if not name or self.contains(name):
            return False
        self._add(name, False, confirm=False)
        self._render()
        self.changed.emit()
        return True

    def set_write(self, name: str, on: bool, *, confirm: bool = True) -> bool:
        """Switch real writing for ``name`` (adds it to the list first)."""
        self.add(name)
        for row_name, check, _row in self._rows:
            if _same_name(row_name, name):
                if on and confirm and not self._confirm_write(row_name):
                    return False
                check.blockSignals(True)
                check.setChecked(on)
                check.blockSignals(False)
                self.changed.emit()
                return True
        return False

    # ---- ui -----------------------------------------------------------------
    def _add(self, name: str, writing: bool, *, confirm: bool) -> None:
        check = QCheckBox("ثبت واقعی در حسابداری")
        check.setChecked(writing)
        check.toggled.connect(lambda on, c=check, n=name: self._toggled(n, c, on))
        remove = widgets.button("حذف از فهرست", icon_name="trash",
                                on_click=lambda n=name: self._remove(n))
        self._rows.append((name, check, remove))

    def _toggled(self, name: str, check: QCheckBox, on: bool) -> None:
        if on and not self._confirm_write(name):
            check.blockSignals(True)
            check.setChecked(False)
            check.blockSignals(False)
        self.changed.emit()

    def _confirm_write(self, name: str) -> bool:
        return widgets.confirm(self, "روشن کردن ثبت واقعی", WRITE_WARNING.format(name=name),
                               confirm_text="بله، ثبت واقعی روشن شود", cancel_text="انصراف",
                               kind="danger")

    def _remove(self, name: str) -> None:
        self._rows = [row for row in self._rows if not _same_name(row[0], name)]
        self._render()
        self.changed.emit()

    def set_choices(self, names: list[str]) -> None:
        self.name_input.set_names(names)

    def _add_typed(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            return
        if self.add(name):
            self.name_input.setText("")

    def _render(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        for index, (name, check, remove) in enumerate(self._rows):
            label = widgets.label(name, bold=True)
            mark_ltr(label)
            self.grid.addWidget(label, index, 0)
            self.grid.addWidget(check, index, 1)
            self.grid.addWidget(remove, index, 2)
        self.grid.setColumnStretch(0, 1)
        self.grid_holder.setVisible(bool(self._rows))
        self.empty_label.setVisible(not self._rows)


class ServerSetupWizard(QWidget):
    """Emits :attr:`completed` with (base_url, certificate_pem) when the server runs."""

    completed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None, *, mode: str = MODE_SETUP) -> None:
        super().__init__(parent)
        self._current: setup.CurrentConfig | None = None
        load_problem = ""
        if mode == MODE_SETTINGS:
            try:
                self._current = setup.read_current_config()
            except setup.SetupError as exc:
                load_problem = exc.message
            if self._current is None:
                mode = MODE_SETUP   # never set up here: the full setup it is
        self.mode = mode
        self.settings_mode = mode == MODE_SETTINGS
        self._steps = [key for key in STEP_TITLES if key != "tools" or self.settings_mode]
        #: v2.9.4: the «مدیر کل» accounts of the running server (None = not known);
        #: a reinstall opens the setup mode on a server that already has its settings
        self._owners: list[dict] | None = None
        try:
            self._existing = self._current is not None or setup.existing_config_port() is not None
        except Exception:  # noqa: BLE001 - an unreadable .env: treat as existing
            self._existing = True
        self._owners_loaded = False
        self._db_list_loaded_for = ""
        title = "تنظیمات سرور فروشگاه" if self.settings_mode else "راه‌اندازی سرور فروشگاه"
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(640, 480)
        self.resize(860, 720)
        # Scoped to this window only: an unscoped "background" would also paint
        # every child, overriding the white-on-blue primary buttons.
        self.setObjectName("WindowRoot")
        self.setStyleSheet(f"QWidget#WindowRoot {{ background: {theme.BACKGROUND}; }}")
        self.toasts = widgets.ToastHost(self)
        self._db_ok = self.settings_mode   # saved settings worked before; a change re-tests
        self._result: tuple[str, str] | None = None
        self._prereq_ok = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)
        root.addWidget(widgets.label(title, size=15, bold=True))
        root.addWidget(widgets.label(
            "مقدارهای فعلی سرور را ببینید و تغییر دهید. رمزها نمایش داده نمی‌شوند؛ خالی "
            "گذاشتن هر رمز یعنی همان رمز قبلی بماند. پس از ذخیره، سرویس سرور دوباره "
            "راه‌اندازی می‌شود." if self.settings_mode else
            "این کار فقط یک‌بار و روی همان رایانه‌ای انجام می‌شود که حسابداری روی آن است.",
            name="Muted", wrap=True))
        if load_problem:
            root.addWidget(widgets.label(load_problem, color=theme.DANGER, wrap=True))

        chips_holder = QWidget()
        chips = widgets.FlowLayout(chips_holder, spacing=6)
        self._chips: list[QLabel] = []
        for index, key in enumerate(self._steps, start=1):
            chip = widgets.label(f"{to_persian_digits(index)}. {STEP_TITLES[key]}")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setMinimumHeight(30)
            chip.setContentsMargins(12, 0, 12, 0)
            chips.addWidget(chip)
            self._chips.append(chip)
        root.addWidget(chips_holder)

        builders = {"checks": self._page_checks, "database": self._page_database,
                    "network": self._page_network, "bots": self._page_bots,
                    "telegram": self._page_telegram,
                    "admin": self._page_admin, "tools": self._page_tools,
                    "run": self._page_run}
        self.stack = QStackedWidget()
        for key in self._steps:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.addWidget(builders[key]())
            page_layout.addStretch(1)       # short pages sit at the top
            self.stack.addWidget(page)
        # v2.8.1: the pages scroll, so the buttons below are always reachable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.stack)
        root.addWidget(scroll, 1)

        nav = QHBoxLayout()
        nav.addStretch(1)
        self.back_button = widgets.button("مرحلهٔ قبل", on_click=self._back)
        self.next_button = widgets.button("ادامه", variant="primary", icon_name="check",
                                          on_click=self._next)
        nav.addWidget(self.next_button)
        nav.addWidget(self.back_button)
        root.addLayout(nav)
        self._step = 0
        self._prefill()
        self._update()
        self._run_checks()

    # ------------------------------------------------------------------ steps
    def _key(self, index: int | None = None) -> str:
        return self._steps[self._step if index is None else index]

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        if not self.property("fitted"):
            self.setProperty("fitted", True)
            widgets.fit_window_to_screen(self)

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
        holder = QWidget()
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        panel = widgets.Panel("اتصال به پایگاه‌دادهٔ حسابداری (سازه حساب)")
        form = _form()
        self.db_server = _line(r".\SQLEXPRESS")
        self.db_server.setText(r".\SQLEXPRESS")
        # v2.9.4: a drop-down of the server's databases (no free typing)
        self.db_name = DatabasePicker()
        name_row = QHBoxLayout()
        name_row.addWidget(self.db_name, 1)
        self.db_list_button = widgets.button("خواندن فهرست", icon_name="refresh",
                                             on_click=lambda: self._load_databases(force=True),
                                             tooltip="فهرست پایگاه‌داده‌های همین سرور SQL")
        name_row.addWidget(self.db_list_button)
        form.addRow(widgets.label("نام سرور SQL:"), self.db_server)
        form.addRow(widgets.label("نام پایگاه‌داده:"), name_row)
        panel.body.addLayout(form)
        self.db_list_status = widgets.label("", name="Muted", wrap=True)
        panel.body.addWidget(self.db_list_status)

        self.auth_sql = QRadioButton("ورود SQL (توصیه می‌شود: کاربر با دسترسی محدود، مثل shopbot)")
        self.auth_windows = QRadioButton("احراز هویت ویندوز با حساب سرویس NT SERVICE\\ShopServer")
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
        # The server runs as the virtual account NT SERVICE\ShopServer (no password).
        self.win_hint = widgets.label(
            "سرور به‌صورت سرویس ویندوز با حساب اختصاصی NT SERVICE\\ShopServer اجرا می‌شود. "
            "«آزمایش اتصال» با همین حساب سرویس انجام می‌شود (نه حساب شما) و «دادن دسترسی» "
            "دقیقاً به همین حساب دسترسی محدود می‌دهد.",
            name="Muted", wrap=True)
        panel.body.addWidget(self.win_hint)
        self.auth_sql.toggled.connect(self._auth_changed)

        row = QHBoxLayout()
        self.db_test_button = widgets.button("ذخیره و آزمایش اتصال", icon_name="wifi",
                                             variant="primary", on_click=self._test_database)
        row.addWidget(self.db_test_button)
        # v2.9.3: when the shop's sign-in may not open the chosen database (e.g. after
        # switching to «hesab5»), what grant_shop_app.ps1 does, with this program's
        # administrator Windows sign-in
        self.grant_button = widgets.button(
            "دادن دسترسی به این دیتابیس", icon_name="key", on_click=self._grant_access,
            tooltip="با حساب مدیر ویندوز همین برنامه، همان دسترسی محدود grant_shop_app.ps1 "
                    "(نقش shop_app) به کاربر فروشگاه روی این پایگاه‌داده داده می‌شود")
        self.grant_button.setVisible(False)
        row.addWidget(self.grant_button)
        row.addStretch(1)
        panel.body.addLayout(row)
        # v2.9.4: one precise reason (bold) and its fix below it
        self.db_result_title = widgets.label("", bold=True, wrap=True)
        self.db_result_title.setVisible(False)
        panel.body.addWidget(self.db_result_title)
        self.db_result = widgets.label("", wrap=True)
        panel.body.addWidget(self.db_result)
        outer.addWidget(panel)

        # ---- v2.8.1: allowed databases and real writing, one by one -----------
        access = widgets.Panel("پایگاه‌داده‌های مجاز و ثبت واقعی")
        access.body.addWidget(widgets.label(
            "سرور فقط در پایگاه‌داده‌ای سفارش ثبت می‌کند که در این فهرست باشد و «ثبت واقعی» "
            "برایش روشن شده باشد. بقیه فقط خوانده می‌شوند (آزمایشی، بدون ثبت). این فهرست "
            "فقط روی همین رایانهٔ سرور تغییر می‌کند.", name="Muted", wrap=True))
        self.db_access = DatabaseAccessList()
        access.body.addWidget(self.db_access)
        self.db_access_status = widgets.label("", wrap=True)
        access.body.addWidget(self.db_access_status)
        outer.addWidget(access)

        for field in (self.db_server, self.db_name, self.db_user, self.db_password):
            field.textEdited.connect(self._db_changed)
        # another SQL Server: its own databases
        self.db_server.editingFinished.connect(lambda: self._load_databases())
        self.db_name.textChanged.connect(self._update_access_status)
        # v2.13.0: picking a database = save, test and (when access is missing) grant
        self.db_name.activated.connect(lambda _i: self._db_picked())
        self.db_access.changed.connect(self._update_access_status)
        self._auth_changed()
        return holder

    def _page_network(self) -> QWidget:
        panel = widgets.Panel("شبکه")
        form = _form()
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(setup.existing_config_port() or setup.DEFAULT_PORT)
        mark_ltr(self.port)
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
        ip_form = _form()
        self.allowed_ips = _line("خالی = همهٔ رایانه‌های همین شبکه (پیش‌فرض)")
        ip_form.addRow(widgets.label("فقط این نشانی‌ها (اختیاری):"), self.allowed_ips)
        panel.body.addLayout(ip_form)
        panel.body.addWidget(widgets.label(
            "مثال: 192.168.10.0/24 یا 192.168.10.5, 192.168.10.6 — با چند نشانی جدا با کاما.",
            name="Muted", wrap=True))
        self.public_warning = widgets.label("", color=theme.DANGER, wrap=True)
        self.public_warning.setVisible(False)
        panel.body.addWidget(self.public_warning)
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        column.addWidget(panel)
        column.addWidget(self._backup_panel())
        return holder

    def _backup_panel(self) -> QWidget:
        """v2.9.1: the encrypted copy of the nightly backup, outside this computer."""
        panel = widgets.Panel("پشتیبان بیرون از سرور")
        panel.body.addWidget(widgets.label(
            "هر شب پس از پشتیبان روزانه، یک نسخهٔ رمزشده (AES-256) در این پوشه گذاشته و بازخوانی "
            "می‌شود؛ فقط آخرین نسخه‌ها نگه داشته می‌شوند. پوشهٔ اشتراکی شبکه هم می‌شود "
            "(\\\\رایانه\\پوشه)؛ سرور با حساب سرویس «NT SERVICE\\ShopServer» می‌نویسد، پس پوشهٔ "
            "اشتراکی باید به رایانهٔ سرور (یا Everyone) اجازهٔ نوشتن بدهد. نسخه‌ها همیشه در زیرپوشهٔ "
            "اختصاصی «ShopServerBackup» نوشته می‌شوند، نه در ریشهٔ درایو. خالی = بدون نسخهٔ بیرونی.",
            name="Muted", wrap=True))
        form = _form()
        self.backup_dir = _line(r"\\PC\ShopBackups")
        # v2.9.2: a share of this computer -> its local folder (the service can write)
        self.backup_dir.editingFinished.connect(self._local_backup_folder)
        form.addRow(widgets.label("پوشهٔ مقصد:"), self.backup_dir)
        pass_row = QHBoxLayout()
        self.backup_pass = _line(f"حداقل {to_persian_digits(setup.BACKUP_PASSPHRASE_MIN)} نویسه",
                                 password=True)
        pass_row.addWidget(self.backup_pass, 1)
        pass_row.addWidget(widgets.button("ساخت عبارت تازه…", icon_name="key",
                                          on_click=self._new_backup_passphrase))
        form.addRow(widgets.label("عبارت رمز پشتیبان:"), pass_row)
        self.backup_keep = QSpinBox()
        self.backup_keep.setRange(3, 60)
        self.backup_keep.setValue(14)
        form.addRow(widgets.label("تعداد نسخه‌های نگه‌داشته:"), self.backup_keep)
        # v2.13.0: a share of ANOTHER computer needs one of its accounts: the service
        # (NT SERVICE\ShopServer) has no user name there ("Access is denied")
        self.backup_user = _line(r"PC\user یا user")
        mark_ltr(self.backup_user)
        self.backup_user_pass = _line(password=True)
        self.backup_user_label = widgets.label("نام کاربری رایانهٔ مقصد:")
        self.backup_user_pass_label = widgets.label("گذرواژهٔ رایانهٔ مقصد:")
        form.addRow(self.backup_user_label, self.backup_user)
        form.addRow(self.backup_user_pass_label, self.backup_user_pass)
        panel.body.addLayout(form)
        self.backup_user_hint = widgets.label(
            "این پوشه روی رایانهٔ دیگری است. سرویس سرور در آن رایانه نام کاربری ندارد؛ نام کاربری "
            "و گذرواژهٔ یک حساب همان رایانه را که اجازهٔ نوشتن در این پوشه دارد وارد کنید (همان "
            "که خودتان برای باز کردن پوشه به کار می‌برید). گذرواژه فقط در پوشهٔ محافظت‌شدهٔ "
            "سرور نگه داشته می‌شود.", name="Muted", wrap=True)
        panel.body.addWidget(self.backup_user_hint)
        self.backup_dir.textChanged.connect(lambda _t: self._backup_folder_changed())
        self._backup_folder_changed()
        row = QHBoxLayout()
        self.backup_test_button = widgets.button("آزمایش", icon_name="check", variant="primary",
                                                 on_click=self._test_backup_folder)
        row.addWidget(self.backup_test_button)
        self.backup_result = widgets.label("", wrap=True)
        row.addWidget(self.backup_result, 1)
        panel.body.addLayout(row)
        panel.body.addWidget(widgets.label(
            "بدون عبارت رمز هیچ نسخه‌ای بیرون نوشته نمی‌شود (در پشتیبان رمز SQL و توکن‌ها هست). "
            "عبارت را روی کاغذ بنویسید و دور از سرور نگه دارید؛ بدون آن نسخه‌ها باز نمی‌شوند.",
            name="Muted", wrap=True))
        return panel

    def _backup_folder_changed(self) -> None:
        """The account fields only for a network folder (\\\\PC\\Share)."""
        network = setup_is_network(self.backup_dir.text())
        for widget in (self.backup_user, self.backup_user_pass, self.backup_user_label,
                       self.backup_user_pass_label, self.backup_user_hint):
            widget.setVisible(network)

    def _new_backup_passphrase(self) -> None:
        phrase = setup.new_backup_passphrase()
        box = QMessageBox(self)
        box.setWindowTitle("عبارت رمز پشتیبان")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("این عبارت را همین حالا روی کاغذ بنویسید؛ دوباره نمایش داده نمی‌شود:\n\n"
                    + phrase + "\n\n(خط تیره‌ها و فاصله‌ها مهم نیستند.)")
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.exec()
        self.backup_pass.setText(phrase)

    def backup_problem(self) -> str:
        folder = self.backup_dir.text().strip()
        typed = self.backup_pass.text()
        saved = bool(((self._current.secrets_set or {}) if self._current else {})
                     .get("BACKUP_PASSPHRASE"))
        if typed and len(setup.normalised_passphrase(typed)) < setup.BACKUP_PASSPHRASE_MIN:
            return (f"عبارت رمز پشتیبان باید دست‌کم {to_persian_digits(setup.BACKUP_PASSPHRASE_MIN)} "
                    "نویسه باشد (یا «ساخت عبارت تازه» را بزنید).")
        if folder and not typed and not saved:
            return "برای پشتیبان بیرون از سرور یک عبارت رمز لازم است («ساخت عبارت تازه»)."
        return ""

    def _local_backup_folder(self) -> bool:
        """v2.9.2: a share of THIS computer (\\\\SERVER\\Share) -> the share's own
        folder. The service account «NT SERVICE\\ShopServer» is refused on its own
        computer's share but can be granted the folder itself. True = changed."""
        from .. import localshare

        folder = self.backup_dir.text().strip()
        if not folder:
            return False
        local = localshare.local_path_for(folder)
        # v2.9.4: never a drive root / whole share: the dedicated sub-folder
        target = setup.backup_target(folder)
        if target == folder:
            return False
        self.backup_dir.setText(target)
        if local and local != folder:
            self._backup_message(
                f"این پوشهٔ اشتراکی روی همین رایانهٔ سرور است؛ مسیر محلی «{target}» گذاشته شد تا "
                "حساب سرویس سرور بتواند در آن بنویسد (دسترسی خودکار داده می‌شود).", None)
        elif setup_is_network(target):
            # v2.13.0: another computer's share: the service needs one of its accounts
            self._backup_message(
                f"نسخه‌ها در پوشهٔ اختصاصی «{target}» روی رایانهٔ دیگری نوشته می‌شوند؛ نام کاربری "
                "و گذرواژهٔ همان رایانه را وارد و «آزمایش» کنید.", None)
        else:
            self._backup_message(
                f"نسخه‌ها در پوشهٔ اختصاصی «{target}» نوشته می‌شوند (هرگز مستقیم در ریشهٔ درایو یا "
                "پوشهٔ اشتراکی)؛ دسترسی حساب سرویس به همین پوشه داده می‌شود.", None)
        return True

    def _test_backup_folder(self) -> None:
        self._local_backup_folder()
        folder = self.backup_dir.text().strip()
        if not folder:
            self._backup_message("ابتدا پوشهٔ مقصد را وارد کنید.", False)
            return
        port = self.port.value()
        settings_mode = self.settings_mode
        network = setup_is_network(folder)
        user = self.backup_user.text().strip() if network else ""
        password = self.backup_user_pass.text() if network else ""
        self.backup_test_button.setEnabled(False)
        self._backup_message("در حال آزمایش…", None)

        def work() -> dict:
            mine = setup.test_backup_folder(folder)
            if mine.get("ok"):
                # v2.9.4: the service account gets Modify on the sub-folder now
                setup.grant_backup_folder(folder)
            service = None
            if settings_mode and mine.get("ok"):
                client = setup.local_server_client(port)
                try:
                    # v2.13.0: with the account of the computer behind a network folder
                    service = client.backup_folder_test(folder, setup.service_key(),
                                                        user=user, password=password)
                except Exception as exc:  # noqa: BLE001 - the server may be stopped
                    service = {"ok": None, "message_fa": "سرور در دسترس نبود؛ آزمایش با حساب "
                                                         f"سرویس انجام نشد ({type(exc).__name__})."}
                finally:
                    client.close()
            return {"mine": mine, "service": service}

        def ok(result: dict) -> None:
            mine, service = result["mine"], result["service"]
            lines = [mine.get("message_fa") or ""]
            good = bool(mine.get("ok"))
            if service is not None:
                lines.append("با حساب سرویس سرور: " + str(service.get("message_fa") or ""))
                good = good and service.get("ok") is not False
            self._backup_message("\n".join(l for l in lines if l), good)

        run_async(work, on_success=ok,
                  on_error=lambda message, _kind: self._backup_message(message, False),
                  on_done=lambda: self.backup_test_button.setEnabled(True))

    def _backup_message(self, text: str, ok: bool | None) -> None:
        color = theme.SUCCESS_DARK if ok else theme.DANGER if ok is False else theme.TEXT_MUTED
        self.backup_result.setText(text)
        self.backup_result.setStyleSheet(f"color: {color};")

    def _page_bots(self) -> QWidget:
        panel = widgets.Panel("ربات‌ها (اختیاری — بعداً هم از «تنظیمات سرور فروشگاه» قابل تنظیم است)")
        form = _form()
        # v2.8.2: no fixed bank text / card: staff send the payment details per order
        self.bale_token = _line("از ربات سازندهٔ بله", password=True)
        self.admin_chats = _line("bale:654321")
        form.addRow(widgets.label("توکن ربات بله:"), self.bale_token)
        form.addRow(widgets.label("گفت‌وگوی مدیران در ربات:"), self.admin_chats)
        # v2.8.1: the Telegram bot (token from BotFather); its api_id / api_hash
        # (my.telegram.org) are on the «تلگرام» page, shared with the reader
        self.telegram_token = _line("از BotFather در تلگرام", password=True)
        form.addRow(widgets.label("توکن ربات تلگرام:"), self.telegram_token)
        panel.body.addLayout(form)
        panel.body.addWidget(widgets.label(
            "ربات تلگرام فقط وقتی روشن می‌شود که توکن آن و «کلید خودم» (api_id و api_hash) "
            "در صفحهٔ «تلگرام» وارد شده باشد.", name="Muted", wrap=True))
        return panel

    def _page_telegram(self) -> QWidget:
        """v2.9.0: the Telegram reader: price lists of the channel + proxy pool."""
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        panel = widgets.Panel("خوانندهٔ تلگرام (لیست قیمت و پراکسی)")
        self.tg_enabled = QCheckBox("لیست قیمت تازهٔ کانال را خودکار بخوان و وارد «لیست قیمت» کن")
        panel.body.addWidget(self.tg_enabled)
        form = _form()
        self.tg_channel = _line(DEFAULT_PRICE_CHANNEL)
        form.addRow(widgets.label("کانال لیست قیمت (بدون @):"), self.tg_channel)
        panel.body.addLayout(form)
        panel.body.addWidget(widgets.label(
            "فقط PDF لیست قیمت خوانده می‌شود (عکس‌ها فعلاً نه)، از همان راه بارگذاری دستی و با همان "
            "قاعدهٔ لیست صبح و عصر. لیست تازه در «مدیریت فروشگاه» اعلام می‌شود و اگر دریافت "
            "نشود به مدیر هشدار داده می‌شود. فقط خواندن؛ هیچ پیامی فرستاده نمی‌شود.",
            name="Muted", wrap=True))
        column.addWidget(panel)

        keys = widgets.Panel("کلید برنامهٔ تلگرام")
        self.tg_key_desktop = QRadioButton("کلید عمومی Telegram Desktop (موقت)")
        self.tg_key_own = QRadioButton("کلید خودم (my.telegram.org)")
        self._tg_key_group = QButtonGroup(self)
        for radio in (self.tg_key_desktop, self.tg_key_own):
            self._tg_key_group.addButton(radio)
            keys.body.addWidget(radio)
        self.tg_key_desktop.setChecked(True)
        self.tg_key_warning = widgets.label(TDESKTOP_WARNING, color=theme.WARNING_TEXT, wrap=True)
        keys.body.addWidget(self.tg_key_warning)
        key_form = _form()
        self.tg_api_id = _line("از my.telegram.org — عدد", password=True)
        self.tg_api_hash = _line("از my.telegram.org — ۳۲ نویسه", password=True)
        key_form.addRow(widgets.label("شناسهٔ برنامه (api_id):"), self.tg_api_id)
        key_form.addRow(widgets.label("کلید برنامه (api_hash):"), self.tg_api_hash)
        keys.body.addLayout(key_form)
        keys.body.addWidget(widgets.label(
            "«کلید خودم» برای ربات تلگرام هم به کار می‌رود. مقدارها هرگز نمایش داده نمی‌شوند.",
            name="Muted", wrap=True))
        self.tg_key_desktop.toggled.connect(self._tg_key_changed)
        column.addWidget(keys)

        login = widgets.Panel("حساب تلگرام و نخستین پراکسی")
        proxy_form = _form()
        self.tg_proxy = _line("tg://proxy?server=…&port=…&secret=…", password=True)
        proxy_form.addRow(widgets.label("پراکسی دستی (برای شروع):"), self.tg_proxy)
        self.shoptg_dir = _line(r"C:\ShopServer\shoptg")
        proxy_form.addRow(widgets.label("پوشهٔ نسخهٔ جداگانهٔ قدیمی (معمولاً خالی):"),
                          self.shoptg_dir)
        login.body.addLayout(proxy_form)
        login.body.addWidget(widgets.label(
            "تا وقتی استخر پراکسی خالی است همین پراکسی به کار می‌رود؛ پس از آن هر روز پراکسی‌های "
            "تازهٔ کانال @ProxyMTProto آزموده و چند پراکسی سالم نگه داشته می‌شود. پراکسی دستیِ "
            "بیشتر را در «سرور فروشگاه» اضافه کنید.", name="Muted", wrap=True))
        row = QHBoxLayout()
        self.tg_login_status = widgets.label("", wrap=True)
        row.addWidget(self.tg_login_status, 1)
        self.tg_login_button = widgets.button("ورود به حساب تلگرام…", variant="primary",
                                              icon_name="key", on_click=self._open_tg_login)
        row.addWidget(self.tg_login_button)
        login.body.addLayout(row)
        column.addWidget(login)
        column.addWidget(self._channels_panel())
        self._tg_key_changed()
        self._update_tg_login_status()
        return holder

    # ------------------------------------------------------------------ v2.9.1: channels
    def _channels_panel(self) -> QWidget:
        panel = widgets.Panel("کانال‌های حساب تلگرام و نقش هر کدام")
        panel.body.addWidget(widgets.label(
            "همهٔ کانال‌هایی که حساب تلگرام فروشگاه عضو آن‌هاست. برای هر کدام نقش بگذارید: فعلاً "
            "«لیست قیمت (گوشی)» و «پراکسی» خوانده می‌شوند؛ «لوازم جانبی» و «گوشی کارکرده» برای "
            "بعد است. عضویت در کانال تازه در «مدیریت فروشگاه» اعلام می‌شود. فقط خواندن؛ هیچ "
            "پیامی فرستاده نمی‌شود.", name="Muted", wrap=True))
        self.channels_table = widgets.DataTable(CHANNEL_HEADERS, key="tg_channels",
                                                fit_width=True, stretch_column=0)
        self.channels_table.set_empty_state(
            "فهرستی نیامده", "خوانندهٔ تلگرام پس از ورود و اتصال، فهرست را می‌فرستد.", "wifi")
        self.channels_table.setMinimumHeight(180)
        panel.body.addWidget(self.channels_table)
        row = QHBoxLayout()
        self.channels_status = widgets.label("", name="Muted", wrap=True)
        row.addWidget(self.channels_status, 1)
        self.channels_button = widgets.button("خواندن فهرست", icon_name="refresh",
                                              on_click=self._load_channels)
        row.addWidget(self.channels_button)
        panel.body.addLayout(row)
        if not self.settings_mode:
            self.channels_button.setEnabled(False)
            self.channels_status.setText("پس از راه‌اندازی سرور، در «تنظیمات سرور» در دسترس است.")
        return panel

    def _load_channels(self) -> None:
        port = self.port.value()
        self.channels_button.setEnabled(False)
        self.channels_status.setText("در حال خواندن…")

        def work() -> dict:
            client = setup.local_server_client(port)
            try:
                return client.telegram_channels(setup.service_key())
            finally:
                client.close()

        run_async(work, on_success=self._show_channels,
                  on_error=lambda message, _kind: self.channels_status.setText(
                      "فهرست خوانده نشد (سرور روشن است؟): " + message),
                  on_done=lambda: self.channels_button.setEnabled(True))

    def _show_channels(self, payload: dict) -> None:
        channels = list((payload or {}).get("channels") or [])
        table = self.channels_table
        table.setRowCount(0)
        for channel in channels:
            i = table.rowCount()
            table.insertRow(i)
            title = str(channel.get("title") or "—")
            if channel.get("present") is False:
                title += " (دیگر عضو نیست)"
            table.set_cell(i, 0, title, bold=True)
            username = channel.get("username")
            table.set_cell(i, 1, f"@{username}" if username else "خصوصی")
            combo = QComboBox()
            for value, text in CHANNEL_ROLES:
                combo.addItem(text, value)
            combo.setCurrentIndex(max(0, combo.findData(str(channel.get("role") or ""))))
            channel_id = int(channel["id"])
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, cid=channel_id: self._set_channel_role(cid, c.currentData()))
            table.set_widget(i, 2, combo)
        table._refresh_states()
        self.channels_status.setText(
            f"{to_persian_digits(len(channels))} کانال." if channels else
            "هنوز فهرستی نیامده؛ پس از ورود حساب تلگرام و اتصال خواننده چند دقیقه صبر کنید.")

    def _set_channel_role(self, channel_id: int, role: str) -> None:
        port = self.port.value()

        def work() -> dict:
            client = setup.local_server_client(port)
            try:
                client.set_channel_role(channel_id, role, setup.service_key())
                return client.telegram_channels(setup.service_key())
            finally:
                client.close()

        run_async(work, on_success=lambda payload: (
            self._show_channels(payload),
            self.channels_status.setText("نقش ذخیره شد؛ خوانندهٔ تلگرام چند دقیقهٔ دیگر از آن پیروی "
                                         "می‌کند.")),
            on_error=lambda message, _kind: widgets.error(self, "نقش کانال", message))

    def _page_admin(self) -> QWidget:
        panel = widgets.Panel("«مدیر کل»")
        # v2.9.4: on a reinstall / in «تنظیمات سرور» the current owner is shown; blank
        # = it stays, the same username + a new password = its password is reset, a
        # new username = one more owner. Nothing here is stored by the installer.
        self.owner_current = widgets.label("", bold=True, wrap=True)
        self.owner_current.setVisible(False)
        panel.body.addWidget(self.owner_current)
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

    # ------------------------------------------------------------------ v2.9.4: owner
    def owner_exists(self) -> bool | None:
        """True / False when the server answered; None when it is not known."""
        if self._owners is not None:
            return bool(self._owners)
        if not self._existing:
            return False            # never set up here: the first owner is made now
        return None

    def owner_names(self) -> list[str]:
        return [str(o.get("username") or "") for o in (self._owners or []) if o.get("username")]

    def _load_owners(self) -> None:
        if self._owners_loaded or not self._existing:
            self._show_owner_state()
            return
        self._owners_loaded = True
        port = self.port.value()
        self.owner_current.setText("در حال خواندن «مدیر کل» فعلی…")
        self.owner_current.setVisible(True)

        def ok(owners: list) -> None:
            self._owners = list(owners or [])
            self._show_owner_state()

        def fail(_message: str, _kind: str) -> None:
            self._owners = None
            self._show_owner_state()

        run_async(setup.current_owners, port, on_success=ok, on_error=fail)

    def _show_owner_state(self) -> None:
        exists = self.owner_exists()
        names = self.owner_names()
        if exists:
            shown = "، ".join(names[:3]) + ("…" if len(names) > 3 else "")
            self.owner_current.setText(f"مدیر کل فعلی: {shown} — اگر خالی بگذارید همان می‌ماند")
            self.admin_note.setText(
                "برای عوض کردن گذرواژهٔ همین مدیر کل، همان نام کاربری و گذرواژهٔ تازه را بنویسید. "
                "نام کاربری تازه = یک «مدیر کل» تازه. گذرواژه‌ها در نصب‌کننده ذخیره نمی‌شوند.")
        elif exists is None:
            self.owner_current.setText(
                "مدیر کل فعلی خوانده نشد (سرور روشن نیست). اگر قبلاً مدیر کل ساخته‌اید، خالی "
                "بگذارید تا همان بماند.")
            self.admin_note.setText(
                "نام کاربری موجود + گذرواژهٔ تازه = عوض شدن گذرواژهٔ همان مدیر کل؛ نام کاربری "
                "تازه = یک «مدیر کل» تازه.")
        else:
            self.owner_current.setText("هنوز «مدیر کل»ی ساخته نشده است؛ نخستین مدیر کل را بسازید.")
            self.admin_note.setText(
                "این حساب مدیر فروشگاه است و بعداً حساب کارکنان را می‌سازد.")
        self.owner_current.setVisible(True)

    def owner_request(self) -> tuple[str, str, str] | None:
        """(username, full name, password) to save, or None = keep the owner."""
        username = to_english_digits(self.admin_username.text()).strip()
        if not username and not self.admin_password.text():
            return None
        return username, self.admin_full_name.text().strip(), self.admin_password.text()

    # ------------------------------------------------------------------ v2.9.4: tools
    def _page_tools(self) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        status = widgets.Panel("راهنمای «کد وضعیت سفارش» (فقط خواندن)")
        status.body.addWidget(widgets.label(
            "پیش از روشن کردن «ثبت واقعی»: همهٔ کدهای وضعیت (Status) سفارش‌های حسابداری با تعداد هر "
            "کدام، و آخرین سفارش‌هایی که خود «سازه حساب» ساخته است. همان سفارش‌ها را در «سازه حساب» "
            "باز کنید و ببینید هر عدد کدام وضعیت است؛ عدد درست را در «کد وضعیت سفارش» بنویسید. "
            "این ابزار هیچ چیزی در حسابداری نمی‌نویسد.", name="Muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(widgets.button("نمایش کدهای وضعیت…", icon_name="search",
                                     on_click=self._open_status_codes))
        row.addStretch(1)
        status.body.addLayout(row)
        column.addWidget(status)

        clean = widgets.Panel("پاک‌سازی داده‌های آزمایشی")
        clean.body.addWidget(widgets.label(
            "پیش از شروع کار واقعی: سفارش‌ها، درخواست‌های خرید، پیام‌ها، رسیدها، مشتریان و پیوند "
            "ربات‌شان، گزارش فعالیت، بایگانی، اعلان‌ها و کاربران آزمایشی (غیر از «مدیر کل») از "
            "داده‌های خود فروشگاه پاک می‌شوند. «مدیر کل»، تنظیمات، نگاشت لیست قیمت، مدل‌های "
            "سایت، پراکسی‌ها و نشست تلگرام می‌مانند. پایگاه‌دادهٔ حسابداری («سازه حساب») هرگز "
            "دست نمی‌خورد. پیش از پاک‌سازی خودکار پشتیبان گرفته می‌شود.", name="Muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(widgets.button("پاک‌سازی داده‌های آزمایشی…", icon_name="trash",
                                     variant="danger", on_click=self._open_cleanup))
        row.addStretch(1)
        clean.body.addLayout(row)
        column.addWidget(clean)
        return holder

    def _open_status_codes(self) -> None:
        from .status_codes import StatusCodesDialog

        port = self.port.value()
        StatusCodesDialog(self, lambda: setup.order_status_codes(port)).exec()

    def _open_cleanup(self) -> None:
        from .cleanup_dialog import CleanupDialog

        CleanupDialog(self, port=self.port.value()).exec()

    def _page_run(self) -> QWidget:
        panel = widgets.Panel("ذخیره و راه‌اندازی دوباره" if self.settings_mode else "راه‌اندازی")
        self.progress = QPlainTextEdit()
        self.progress.setReadOnly(True)
        self.progress.setMinimumHeight(160)
        panel.body.addWidget(self.progress)
        self.final_box = QWidget()
        final = QVBoxLayout(self.final_box)
        final.setContentsMargins(0, 0, 0, 0)
        final.addWidget(widgets.label("سرور آماده است. روی رایانهٔ هر کارمند «مدیریت فروشگاه» را "
                                      "نصب کنید و این نشانی را وارد کنید:", wrap=True))
        self.final_address = widgets.label("", size=13, bold=True)
        mark_ltr(self.final_address)
        self.final_address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        final.addWidget(self.final_address)
        final.addWidget(widgets.label("اثرانگشت امنیتی که باید روی رایانهٔ کارمند همین باشد:",
                                      wrap=True))
        self.final_fingerprint = widgets.label("", size=15, bold=True)
        mark_ltr(self.final_fingerprint)
        self.final_fingerprint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        final.addWidget(self.final_fingerprint)
        self.final_box.setVisible(False)
        panel.body.addWidget(self.final_box)
        return panel

    # ------------------------------------------------------------------ prefill
    def _prefill(self) -> None:
        current = self._current
        if current is None:
            self.db_access.set_values([], [])
            self._update_access_status()
            return
        self.db_server.setText(current.db_server or r".\SQLEXPRESS")
        self.db_name.setText(current.db_name)
        (self.auth_windows if current.db_trusted else self.auth_sql).setChecked(True)
        self.db_user.setText(current.db_user)
        if current.db_password_set:
            self.db_password.setPlaceholderText(KEEP_SECRET)
        self.port.setValue(current.port)
        self.allowed_ips.setText(current.allowed_ips)
        self.admin_chats.setText(current.admin_chats)
        self.shoptg_dir.setText(current.shoptg_dir)
        self.tg_enabled.setChecked(current.tg_reader_enabled)
        (self.tg_key_own if current.tg_api_preset == "custom" else self.tg_key_desktop).setChecked(True)
        self.tg_channel.setText(current.tg_price_channel)
        self.backup_dir.setText(current.backup_copy_dir)
        self.backup_keep.setValue(current.backup_keep_days or 14)
        self.backup_user.setText(current.backup_share_user)
        self._backup_folder_changed()
        secrets = current.secrets_set or {}
        for key, field in self._secret_fields().items():
            if secrets.get(key):
                field.setPlaceholderText(KEEP_SECRET)
        self.db_access.set_values(current.allowed_databases or [], current.write_databases or [])
        self._db_ok = True
        self._update_access_status()

    def _secret_fields(self) -> dict[str, QLineEdit]:
        return {"BALE_TOKEN": self.bale_token, "TELEGRAM_BOT_TOKEN": self.telegram_token,
                "TG_API_ID": self.tg_api_id, "TG_API_HASH": self.tg_api_hash,
                "TG_PROXY": self.tg_proxy, "BACKUP_PASSPHRASE": self.backup_pass,
                "BACKUP_SHARE_PASSWORD": self.backup_user_pass}

    # ------------------------------------------------------------------ telegram (v2.9.0)
    def tg_preset(self) -> str:
        return "custom" if self.tg_key_own.isChecked() else "tdesktop"

    def _tg_key_changed(self, *_args) -> None:
        own = self.tg_key_own.isChecked()
        self.tg_api_id.setEnabled(own)
        self.tg_api_hash.setEnabled(own)
        self.tg_key_warning.setVisible(not own)

    def _update_tg_login_status(self) -> None:
        if setup.telegram_logged_in():
            self.tg_login_status.setText("✔ حساب تلگرام وارد شده است (نشست رمزشده روی این سرور).")
            self.tg_login_status.setStyleSheet(f"color: {theme.SUCCESS_DARK};")
            self.tg_login_button.setText("ورود دوباره…")
        else:
            self.tg_login_status.setText("هنوز وارد حساب تلگرام نشده‌اید.")
            self.tg_login_status.setStyleSheet(f"color: {theme.WARNING_TEXT};")
            self.tg_login_button.setText("ورود به حساب تلگرام…")

    def telegram_problem(self) -> str:
        channel = self.tg_channel.text().strip().lstrip("@") or DEFAULT_PRICE_CHANNEL
        if not _CHANNEL_RE.match(channel):
            return "نام کانال باید فقط حرف انگلیسی، عدد و _ باشد (۵ تا ۳۲ نویسه)."
        api_id = to_english_digits(self.tg_api_id.text()).strip()
        if self.tg_preset() == "custom":
            if api_id and not api_id.isdigit():
                return "api_id باید فقط عدد باشد."
            api_hash = self.tg_api_hash.text().strip()
            if api_hash and not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
                return "api_hash باید ۳۲ نویسهٔ ۰-۹ و a-f باشد."
            saved = (self._current.secrets_set or {}) if self._current else {}
            if not (api_id or saved.get("TG_API_ID")) or not (api_hash or saved.get("TG_API_HASH")):
                return "برای «کلید خودم» هر دو مقدار api_id و api_hash لازم است."
        proxy = self.tg_proxy.text().strip()
        if proxy and not _PROXY_RE.match(proxy):
            return "پراکسی باید پیوند tg://proxy?… یا https://t.me/proxy?… باشد."
        return ""

    def _open_tg_login(self) -> None:
        problem = self.telegram_problem()
        if problem:
            widgets.error(self, "تلگرام", problem)
            return
        from .telegram_login import TelegramLoginDialog

        custom = self.tg_preset() == "custom"
        dialog = TelegramLoginDialog(
            self, preset=self.tg_preset(),
            api_id=to_english_digits(self.tg_api_id.text()).strip() if custom else "",
            api_hash=self.tg_api_hash.text().strip() if custom else "",
            proxy=self.tg_proxy.text().strip())
        dialog.exec()
        self._update_tg_login_status()

    # ------------------------------------------------------------------ helpers
    def _auth_changed(self) -> None:
        sql = self.auth_sql.isChecked()
        self.db_user.setEnabled(sql)
        self.db_password.setEnabled(sql)
        self.win_hint.setVisible(not sql)
        self._db_changed()

    def _db_changed(self, *_args) -> None:
        self._db_ok = False

    def _password_kept(self) -> bool:
        return (self._current is not None and self._current.db_password_set
                and not self.db_password.text())

    def _db_config(self) -> setup.DatabaseConfig:
        return setup.DatabaseConfig(
            server=self.db_server.text().strip(),
            database=self.db_name.text().strip(),
            trusted=self.auth_windows.isChecked(),
            user=self.db_user.text().strip(),
            password=self.db_password.text(),
        )

    def database_state_text(self) -> tuple[str, str]:
        """(text, colour) for the chosen database: allowed / writing / read only."""
        name = self.db_name.text().strip()
        if not name:
            return "نام پایگاه‌داده را وارد کنید.", theme.TEXT_MUTED
        if not self.db_access.contains(name):
            return (f"«{name}» در فهرست مجاز نیست: سرور فقط از آن می‌خواند و هیچ سفارشی در "
                    "آن ثبت نمی‌شود. برای ثبت، آن را به فهرست اضافه و «ثبت واقعی» را روشن کنید.",
                    theme.WARNING_TEXT)
        if not self.db_access.write_on(name):
            return (f"«{name}» مجاز است ولی «ثبت واقعی» برایش روشن نیست: سفارش‌ها آزمایشی "
                    "(بدون ثبت در حسابداری) پردازش می‌شوند.", theme.WARNING_TEXT)
        return (f"ثبت واقعی در «{name}» روشن است: سفارش‌های تأییدشده در «سازه حساب» ثبت "
                "می‌شوند (کد وضعیت سفارش هم باید در صفحهٔ «سرور فروشگاه» تنظیم شده باشد).",
                theme.DANGER)

    def _update_access_status(self, *_args) -> None:
        text, color = self.database_state_text()
        self.db_access_status.setText(text)
        self.db_access_status.setStyleSheet(f"color: {color};")

    def _update(self) -> None:
        self.stack.setCurrentIndex(self._step)
        # only the shown page counts for the height (a short page is not stretched
        # to the tallest one, and the scroll bar appears only when needed)
        for index in range(self.stack.count()):
            policy = QSizePolicy.Policy.Preferred if index == self._step else QSizePolicy.Policy.Ignored
            self.stack.widget(index).setSizePolicy(policy, policy)
        self.stack.adjustSize()
        last = len(self._steps) - 1
        self.back_button.setEnabled(0 < self._step < last)
        self.next_button.setText(("ذخیره و راه‌اندازی دوباره" if self.settings_mode else "راه‌اندازی")
                                 if self._step == last - 1 else
                                 "پایان" if self._step == last else "ادامه")
        for index, chip in enumerate(self._chips):
            if index == self._step:
                chip.setStyleSheet(f"background: {theme.PRIMARY}; color: #FFFFFF; "
                                   "border-radius: 10px; font-weight: 700; padding: 0 12px;")
            elif index < self._step:
                chip.setStyleSheet(f"background: {theme.SUCCESS_LIGHT}; color: {theme.SUCCESS_DARK}; "
                                   "border-radius: 10px; font-weight: 600; padding: 0 12px;")
            else:
                chip.setStyleSheet(f"background: {theme.SURFACE}; color: {theme.TEXT_MUTED}; "
                                   f"border: 1px solid {theme.BORDER}; border-radius: 10px; "
                                   "padding: 0 12px;")
        # v2.9.4: what a page needs from the server is read when it is shown
        key = self._key()
        if key == "database":
            self._load_databases()
        elif key == "admin":
            self._load_owners()

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
                lines.append("ℹ تنظیمات فعلی سرور پیدا شد؛ کلیدهای موجود حفظ می‌شوند.")
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
    def _db_input_problem(self, db: setup.DatabaseConfig) -> str:
        if not db.server:
            return "نام سرور SQL را وارد کنید."
        if not db.database:
            return "نام پایگاه‌داده را از فهرست انتخاب کنید (اگر فهرست خالی است «خواندن فهرست»)."
        if not db.trusted and (not db.user or not (db.password or self._password_kept())):
            return "نام کاربری و گذرواژهٔ SQL را وارد کنید."
        return ""

    # ---- v2.9.4: the database list ------------------------------------------------
    def _load_databases(self, *, force: bool = False) -> None:
        server = self.db_server.text().strip()
        if not server:
            self.db_list_status.setText("نام سرور SQL را وارد کنید.")
            return
        sql = self.auth_sql.isChecked()
        key = f"{server.lower()}|{sql}|{self.db_user.text().strip().lower()}"
        if not force and key == self._db_list_loaded_for:
            return
        self._db_list_loaded_for = key
        user = self.db_user.text().strip() if sql else ""
        password = self.db_password.text() if sql else ""
        self.db_list_button.setEnabled(False)
        self.db_list_status.setText("در حال خواندن فهرست پایگاه‌داده‌های سرور…")
        self.db_list_status.setStyleSheet("")

        def ok(names: list) -> None:
            self.db_name.set_names(names)
            self.db_access.set_choices(names)
            if names:
                self.db_list_status.setText(
                    f"{to_persian_digits(len(names))} پایگاه‌داده روی این سرور پیدا شد؛ یکی را "
                    "انتخاب کنید.")
            else:
                self.db_list_status.setText("روی این سرور هیچ پایگاه‌دادهٔ کاربری پیدا نشد.")
            self._update_access_status()

        def fail(message: str, _kind: str) -> None:
            self._db_list_loaded_for = ""
            self.db_list_status.setText("فهرست خوانده نشد: " + message)
            self.db_list_status.setStyleSheet(f"color: {theme.DANGER};")

        run_async(setup.list_databases, server, user=user, password=password, on_success=ok,
                  on_error=fail, on_done=lambda: self.db_list_button.setEnabled(True))

    def _db_picked(self) -> None:
        """v2.13.0: a database chosen from the list is saved and tested at once; if
        the shop's account may not open it, access is given automatically (the
        2.9.4 drop-down only tested, and with a Persian answer not even that)."""
        db = self._db_config()
        if not db.database or self._db_input_problem(db):
            return
        self._test_database(auto_grant=True)

    def _test_database(self, auto_grant: bool = False) -> None:
        """«ذخیره و آزمایش اتصال» (the button: test only); ``auto_grant`` (v2.13.0, a
        database picked from the list): «دسترسی نیست» is answered with the grant."""
        db = self._db_config()
        problem = self._db_input_problem(db)
        if problem:
            self._db_message(problem, False)
            return
        self.db_test_button.setEnabled(False)
        self._db_message("در حال ذخیره و آزمایش…", None)
        port = self.port.value()
        windows = db.trusted
        settings_mode = self.settings_mode

        def work() -> dict:
            setup.harden_data_dir()
            setup.write_config(db, port=port)
            result = setup.check_database()
            if windows and settings_mode:
                # like the backup test: the running service itself, when it answers
                result["service_live"] = setup.service_db_check(port, db.server, db.database)
            return result

        def ok(result: dict) -> None:
            live = result.get("service_live")
            if live is not None and not live.get("ok"):
                self._db_ok = False
                self._db_message(
                    "سرویس سرور (با حساب خودش) به این پایگاه‌داده وصل نشد: "
                    + str(live.get("message_fa") or ""), False,
                    title="دسترسی نیست")
                self.grant_button.setVisible(True)
                if auto_grant:
                    self._grant_access(confirm=False)
                return
            self._db_ok = True
            groups = to_persian_digits(result.get("groups", 0))
            if result.get("as_service") or (live or {}).get("ok"):
                text = (f"اتصال با حساب خود سرویس («{result.get('login')}») برقرار شد "
                        f"({groups} گروه کالا).")
            elif result.get("windows"):
                text = (f"اتصال برقرار شد ({groups} گروه کالا). "
                        + str(result.get("note_fa") or ""))
            else:
                text = f"اتصال برقرار شد ({groups} گروه کالا)."
            self._db_message(text.strip(), True)

        def fail(message: str, kind: str) -> None:
            self._db_ok = False
            self._show_db_error(message, kind)
            if auto_grant and kind == setup.DatabaseAccessError.kind:
                self._grant_access(confirm=False)

        self.grant_button.setVisible(False)
        run_async(work, on_success=ok, on_error=fail,
                  on_done=lambda: self.db_test_button.setEnabled(True))

    #: v2.9.4: the title of each precise failure (the fix comes from the server)
    DB_ERROR_TITLES = {"db_server": "SQL Server پیدا نشد", "db_missing": "این پایگاه‌داده وجود ندارد",
                       "db_access": "دسترسی نیست",
                       "db_password": "نام کاربری یا گذرواژهٔ SQL نادرست است",
                       "db_remote": "احراز هویت ویندوز به SQL Server رایانهٔ دیگر نمی‌رسد"}

    def _show_db_error(self, message: str, kind: str) -> None:
        title = self.DB_ERROR_TITLES.get(kind, "اتصال برقرار نشد")
        fix = message.split(":", 1)[1].strip() if message.startswith(title + ":") else message
        self._db_message(fix, False, title=title)
        # «دادن دسترسی به این دیتابیس» only when access is what is missing
        self.grant_button.setVisible(kind == setup.DatabaseAccessError.kind)
        if kind == "db_missing":
            self._load_databases(force=True)

    def shop_login_name(self) -> str:
        """The account the service connects with (the one «دادن دسترسی» grants)."""
        if self.auth_windows.isChecked():
            return setup.SERVICE_ACCOUNT
        return self.db_user.text().strip()

    def _grant_access(self, confirm: bool = True) -> None:
        """``confirm=False`` (v2.13.0): the automatic grant after picking a database."""
        database = self.db_name.text().strip()
        login = self.shop_login_name()
        if confirm and not widgets.confirm(
                self, "دادن دسترسی به این دیتابیس",
                f"با حساب مدیر ویندوز همین برنامه، به «{login}» روی «{database}» همان دسترسی "
                "محدودی داده می‌شود که grant_shop_app.ps1 می‌دهد (نقش shop_app: خواندن کالا و "
                "موجودی، ثبت سفارش و مشتری؛ بدون حذف و بدون دیدن تنظیمات). اگر کاربر وجود "
                "نداشته باشد ساخته می‌شود. حساب ویندوز شما باید در SQL Server «sysadmin» باشد.\n"
                "ادامه می‌دهید؟", confirm_text="بله، دسترسی بده", kind="warning"):
            return
        self.grant_button.setEnabled(False)
        self.db_test_button.setEnabled(False)
        self._db_message(f"حساب «{login}» به «{database}» دسترسی ندارد؛ در حال دادن خودکار "
                         "دسترسی محدود (نقش shop_app) و آزمایش دوباره…" if not confirm else
                         "در حال دادن دسترسی…", None)

        def ok(result: dict) -> None:
            self._db_ok = bool(result.get("check_ok"))
            self._db_message(setup.grant_result_text(result), self._db_ok,
                             title="" if self._db_ok else "دسترسی هنوز کامل نیست")
            self.grant_button.setVisible(not self._db_ok)

        def fail(message: str, _kind: str) -> None:
            if confirm:
                self._db_message(message, False, title="دسترسی داده نشد")
            else:
                self._db_message("دادن خودکار دسترسی ممکن نشد: " + message, False,
                                 title="دسترسی نیست")

        def done() -> None:
            self.grant_button.setEnabled(True)
            self.db_test_button.setEnabled(True)

        run_async(setup.grant_database_access, on_success=ok, on_error=fail, on_done=done)

    def _db_message(self, text: str, ok: bool | None, *, title: str = "") -> None:
        color = theme.SUCCESS_DARK if ok else theme.DANGER if ok is False else theme.TEXT_MUTED
        self.db_result_title.setText(("✖ " if ok is False else "") + title)
        self.db_result_title.setVisible(bool(title))
        self.db_result_title.setStyleSheet(f"color: {color};")
        self.db_result.setText(text)
        self.db_result.setStyleSheet(f"color: {color};")

    # ------------------------------------------------------------------ navigation
    def _back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._update()

    def _next(self) -> None:
        key = self._key()
        if key == "checks":
            if not self._prereq_ok:
                widgets.error(self, "پیش‌نیازها", "ابتدا موارد علامت‌خورده با ✖ را برطرف کنید.")
                return
        elif key == "database":
            if not self._db_ok:
                widgets.error(self, "حسابداری", "ابتدا «ذخیره و آزمایش اتصال» را با موفقیت انجام دهید.")
                return
        elif key == "network":
            try:
                setup.parse_allowed_ips(self.allowed_ips.text())
            except setup.SetupError as exc:
                widgets.error(self, "شبکه", exc.message)
                return
            problem = self.backup_problem()
            if problem:
                widgets.error(self, "پشتیبان", problem)
                return
        elif key == "telegram":
            problem = self.telegram_problem()
            if problem:
                widgets.error(self, "تلگرام", problem)
                return
        elif key == "admin":
            if not self._validate_admin():
                return
        elif key == "run":
            if self._result:
                self.completed.emit(*self._result)
            self.close()
            return
        if self._key(self._step + 1) == "run":
            if not self._confirm_run():
                return
            self._step += 1
            self._update()
            self.next_button.setEnabled(False)
            self.back_button.setEnabled(False)
            self._execute()
            return
        self._step += 1
        self._update()

    def _confirm_run(self) -> bool:
        writing = self.db_access.writing()
        before = list((self._current.write_databases if self._current else None) or [])
        added = [n for n in writing if not any(_same_name(n, b) for b in before)]
        if not added:
            return True
        return widgets.confirm(
            self, "ثبت واقعی در حسابداری",
            "ثبت واقعی برای این پایگاه‌داده‌ها روشن می‌شود: " + "، ".join(f"«{n}»" for n in added)
            + "\nپس از این، سفارش‌های تأییدشده در «سازه حساب» ثبت می‌شوند. ذخیره شود؟",
            confirm_text="ذخیره", cancel_text="بازگشت", kind="danger")

    def _validate_admin(self) -> bool:
        """v2.9.4: blank = keep the current owner (when there is one); otherwise a
        username and a strong password (the full name only for the first owner)."""
        self.admin_error.setText("")
        name = self.admin_full_name.text().strip()
        username = to_english_digits(self.admin_username.text()).strip()
        password = self.admin_password.text()
        exists = self.owner_exists()
        if not username and not password and not self.admin_confirm.text():
            if exists is False:
                self.admin_error.setText("هنوز «مدیر کل»ی نیست؛ نام، نام کاربری و گذرواژه را "
                                         "وارد کنید.")
            return not self.admin_error.text()
        if not name and exists is False:
            self.admin_error.setText("نام و نام خانوادگی را وارد کنید.")
        elif not username:
            self.admin_error.setText("نام کاربری را بنویسید (برای عوض کردن گذرواژه، همان نام "
                                     "کاربری مدیر کل فعلی).")
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
    def config_extra(self) -> dict:
        """The settings beside the database for ``write_config``: an untouched
        secret is ``None`` (keep the saved one); an emptied text clears it."""
        extra = {
            "firewall_allowed_ips": " ".join(setup.parse_allowed_ips(self.allowed_ips.text())),
            "shoptg_dir": self.shoptg_dir.text().strip(),
            "admin_chat_ids": self.admin_chats.text().strip(),
            "allowed_databases": ",".join(self.db_access.allowed()),
            "write_databases": ",".join(self.db_access.writing()),
        }
        for field_key, field in (("bale_token", self.bale_token),
                                 ("telegram_bot_token", self.telegram_token),
                                 ("tg_api_id", self.tg_api_id),
                                 ("tg_api_hash", self.tg_api_hash),
                                 ("tg_proxy", self.tg_proxy)):
            value = to_english_digits(field.text()).strip()
            extra[field_key] = value or None
        # v2.9.0: the Telegram reader
        extra["tg_reader_enabled"] = self.tg_enabled.isChecked()
        extra["tg_api_preset"] = self.tg_preset()
        extra["tg_price_channel"] = self.tg_channel.text().strip().lstrip("@") or DEFAULT_PRICE_CHANNEL
        # v2.9.1: the off-server backup copy (an untouched passphrase = keep the saved one)
        self._local_backup_folder()
        extra["backup_copy_dir"] = self.backup_dir.text().strip()
        extra["backup_keep_days"] = str(self.backup_keep.value())
        extra["backup_passphrase"] = self.backup_pass.text().strip() or None
        # v2.13.0: the account of the computer behind a network folder (an untouched
        # password = keep the saved one; a local folder clears both)
        network = setup_is_network(self.backup_dir.text())
        extra["backup_share_user"] = self.backup_user.text().strip() if network else ""
        extra["backup_share_password"] = (self.backup_user_pass.text() or None) if network else ""
        return extra

    def _execute(self) -> None:
        db = self._db_config()
        port = self.port.value()
        allowed_ips = self.allowed_ips.text().strip()
        extra = self.config_extra()
        settings_mode = self.settings_mode
        # v2.9.4: None = keep the current owner; never stored anywhere but the server
        admin = self.owner_request()
        if admin is not None:
            admin = (to_english_digits(admin[0]), admin[1], admin[2])

        def work(on_progress) -> tuple[str, str, str]:
            on_progress("محدود کردن دسترسی پوشهٔ داده")
            setup.harden_data_dir()
            on_progress("نوشتن تنظیمات سرور")
            setup.write_config(db, port=port, extra=extra)
            on_progress("ثبت (به‌روزرسانی) سرویس ویندوز «ShopServer»")
            setup.install_service()
            on_progress("باز کردن دیوار آتش برای شبکهٔ محلی")
            setup.open_firewall(port, allowed_ips)
            if settings_mode:
                on_progress("راه‌اندازی دوبارهٔ سرور با تنظیمات تازه")
                setup.restart_service()
            else:
                on_progress("روشن کردن سرور")
                setup.start_service()
            on_progress("منتظر آماده شدن سرور (تا ۹۰ ثانیه)")
            pem, fingerprint = setup.wait_until_ready(port)
            base_url = f"https://127.0.0.1:{port}"
            client = ShopApiClient(base_url, server_cert_pem=pem, timeout=15)
            try:
                if client.auth_status().get("bootstrap_required"):
                    if admin is None:
                        on_progress("هنوز مدیر کلی ساخته نشده؛ در مرحلهٔ «مدیر کل» نام کاربری و "
                                    "گذرواژه را وارد و دوباره ذخیره کنید")
                    else:
                        on_progress("ساخت مدیر کل")
                        client.bootstrap(setup.service_key(), *admin)
                elif admin is not None:
                    answer = client.set_owner(admin[0], admin[1], admin[2], setup.service_key())
                    on_progress(f"گذرواژهٔ مدیر کل «{answer.get('username')}» عوض شد"
                                if answer.get("action") == "password_reset" else
                                f"مدیر کل تازه «{answer.get('username')}» ساخته شد")
                else:
                    on_progress("مدیر کل فعلی بدون تغییر ماند")
            finally:
                client.close()
            return base_url, pem, fingerprint

        def ok(result: tuple[str, str, str]) -> None:
            base_url, pem, fingerprint = result
            self._result = (base_url, pem)
            self._say("تنظیمات ذخیره و سرور دوباره راه‌اندازی شد." if settings_mode
                      else "سرور فروشگاه آماده است.", True)
            addresses = setup.lan_addresses() or ["<نشانی این رایانه>"]
            self.final_address.setText("\n".join(f"https://{a}:{port}" for a in addresses))
            self.final_fingerprint.setText(short_fingerprint(fingerprint))
            self.final_box.setVisible(True)
            self.next_button.setEnabled(True)
            log.info("server %s finished", "settings" if settings_mode else "setup")

        def fail(message: str, _kind: str) -> None:
            self._say(message, False)
            self.back_button.setEnabled(True)
            self._step = len(self._steps) - 2
            widgets.error(self, "تنظیمات سرور" if settings_mode else "راه‌اندازی سرور", message)
            self._update()

        run_async(work, on_success=ok, on_error=fail, on_progress=lambda m: self._say(m))
