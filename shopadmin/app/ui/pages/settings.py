"""صفحهٔ تنظیمات — آدرس سرور، بازه‌ها، اعلان‌ها، گذرواژهٔ خود و مشاهدهٔ لاگ.

آدرس سرور و ترجیحات اعلان فقط روی همین رایانه ذخیره می‌شوند. گذرواژه روی
سرور تغییر می‌کند. هیچ کلید یا رمزی روی این رایانه نگه داشته نمی‌شود.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import autostart
from ...logging_setup import get_logger
from ...paths import APP_VERSION, data_dir, db_path, log_path
from ...edition import is_server_edition
from ...permissions import (
    SETTINGS_CHANGE_OWN_PASSWORD,
    SETTINGS_EDIT_CONNECTION,
    SETTINGS_EDIT_GENERAL,
    SETTINGS_VIEW_LOG,
)
from ...persian import format_shamsi, to_persian_digits
from ...statuses import role_fa
from .. import theme, widgets
from ..async_utils import run_async
from ..base_page import BasePage
from ..rtl import RIGHT

log = get_logger("settings")


class SettingsPage(BasePage):
    title = "تنظیمات برنامه"
    subtitle = "همین رایانه: اتصال، اعلان‌ها، بازه‌های به‌روزرسانی، ظاهر و پرونده‌ها"
    help_text = ("تنظیمات همین رایانه برای همهٔ کاربران. تنظیمات مشترک فروشگاه در "
                 "«تنظیمات سرور فروشگاه» است.")
    #: v2.8.2: a form page: never reloaded by itself
    auto_refreshable = False
    refresh_on_server_events = False
    reload_on_data_change = False

    def build_body(self) -> None:
        from PySide6.QtWidgets import QScrollArea

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(16)

        layout.addWidget(self._build_connection_panel())
        layout.addWidget(self._build_general_panel())
        layout.addWidget(self._build_notifications_panel())
        layout.addWidget(self._build_appearance_panel())
        layout.addWidget(self._build_password_panel())
        layout.addWidget(self._build_about_panel())
        layout.addStretch(1)

        scroll.setWidget(container)
        self.body.addWidget(scroll, 1)

        self._reload_values()

    def load(self) -> None:
        """Settings live in the local database, so this only re-reads them."""
        self._reload_values()

    # ------------------------------------------------------------------ panels
    def _build_connection_panel(self) -> QWidget:
        panel = widgets.Panel("اتصال به سرور فروشگاه")

        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("http://192.168.1.10:8000")
        self.base_url_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        form = QFormLayout()
        form.setLabelAlignment(RIGHT)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.addRow(widgets.label("آدرس سرور:"), self.base_url_input)
        panel.body.addLayout(form)

        self.connection_hint = widgets.label("", name="Muted", wrap=True)
        panel.body.addWidget(self.connection_hint)

        if not self.context.can(SETTINGS_EDIT_CONNECTION):
            # Only the Super Admin may point this computer at another server.
            self.base_url_input.setEnabled(False)
            self.connection_hint.setText(
                "تغییر آدرس سرور فقط توسط مدیر یا دسترسی «تنظیمات سرور فروشگاه — تغییر» امکان‌پذیر است."
            )
        else:
            self.connection_hint.setText(
                "پس از تغییر آدرس، باید دوباره وارد شوید. هیچ کلید یا رمزی روی این "
                "رایانه ذخیره نمی‌شود."
            )

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.test_button = widgets.button(
            "آزمایش اتصال", icon_name="wifi", variant="primary", on_click=self._test_connection
        )
        self.save_connection_button = widgets.button(
            "ذخیرهٔ تنظیمات اتصال", icon_name="save", on_click=self._save_connection
        )
        self.info_button = widgets.button(
            "اطلاعات سرور", icon_name="server", on_click=self._show_server_info
        )
        self.save_connection_button.setEnabled(self.context.can(SETTINGS_EDIT_CONNECTION))
        buttons.addWidget(self.test_button)
        buttons.addWidget(self.save_connection_button)
        buttons.addWidget(self.info_button)
        buttons.addStretch(1)
        panel.body.addLayout(buttons)

        self.connection_status = widgets.label("", wrap=True)
        panel.body.addWidget(self.connection_status)
        return panel

    def _build_general_panel(self) -> QWidget:
        panel = widgets.Panel("بازه‌های زمانی")
        form = QFormLayout()
        form.setLabelAlignment(RIGHT)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(0, 3600)
        self.refresh_spin.setSuffix(" ثانیه")
        self.refresh_spin.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.refresh_spin.setSpecialValueText("خاموش")

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 480)
        self.timeout_spin.setSuffix(" دقیقه")
        self.timeout_spin.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        form.addRow(widgets.label("به‌روزرسانی خودکار:"), self.refresh_spin)
        form.addRow(widgets.label("پایان خودکار نشست:"), self.timeout_spin)
        panel.body.addLayout(form)

        hint = widgets.label(
            "برای خاموش کردن به‌روزرسانی خودکار، مقدار صفر بگذارید. "
            "پس از پایان زمان نشست، برای ادامه باید دوباره وارد شوید.",
            name="Muted", wrap=True,
        )
        panel.body.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_general_button = widgets.button(
            "ذخیره", icon_name="save", variant="primary", on_click=self._save_general
        )
        self.save_general_button.setEnabled(self.context.can(SETTINGS_EDIT_GENERAL))
        if not self.context.can(SETTINGS_EDIT_GENERAL):
            hint.setText(hint.text() + " (تغییر این مقادیر برای نقش شما مجاز نیست.)")
        buttons.addWidget(self.save_general_button)
        panel.body.addLayout(buttons)
        return panel

    def _build_appearance_panel(self) -> QWidget:
        """v2.9.0: palette × light/dark × «جلوه‌ها», per computer (also in
        «اعلان‌ها و ظاهر» for every user)."""
        from ..appearance import AppearancePicker

        panel = widgets.Panel("ظاهر برنامه (همین رایانه)")
        self.appearance = AppearancePicker(self.context.store)
        panel.body.addWidget(self.appearance)
        row = QHBoxLayout()
        row.addStretch(1)
        save = widgets.button("ذخیره", icon_name="save", variant="primary",
                              on_click=self._save_appearance)
        row.addWidget(save)
        panel.body.addLayout(row)
        return panel

    def _save_appearance(self) -> None:
        from ..appearance import offer_restart

        if self.appearance.save():
            offer_restart(self, self.context)
        else:
            self.notify_success("ذخیره شد.")

    def _build_notifications_panel(self) -> QWidget:
        panel = widgets.Panel("اعلان‌ها (همین رایانه)")
        self.notify_desktop_check = QCheckBox("نمایش اعلان ویندوز برای مشتری، سفارش و فیش جدید")
        self.notify_sound_check = QCheckBox("پخش صدای اعلان")
        self.close_to_tray_check = QCheckBox(
            "با بستن پنجره، برنامه کنار ساعت ویندوز فعال بماند تا اعلان‌ها برسد")
        self.autostart_check = QCheckBox(
            "با ورود به ویندوز، برنامه خودکار کنار ساعت ویندوز اجرا شود (پنجره باز نمی‌شود)")
        self.sazeh_watch_check = QCheckBox(
            "با باز شدن «سازه حساب» روی این رایانه، تعداد سفارش‌ها و مشتریان منتظر را یادآوری کن")
        for check in (self.notify_desktop_check, self.notify_sound_check,
                      self.close_to_tray_check, self.autostart_check, self.sazeh_watch_check):
            panel.body.addWidget(check)

        form = QFormLayout()
        form.setLabelAlignment(RIGHT)
        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(2, 600)
        self.poll_spin.setSuffix(" ثانیه")
        self.poll_spin.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        form.addRow(widgets.label("بررسی موارد جدید هر:"), self.poll_spin)
        panel.body.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(widgets.button("ذخیره", icon_name="save", variant="primary",
                                         on_click=self._save_notifications))
        panel.body.addLayout(buttons)
        return panel

    def _build_password_panel(self) -> QWidget:
        panel = widgets.Panel("تغییر گذرواژهٔ من")
        form = QFormLayout()
        form.setLabelAlignment(RIGHT)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self.current_password = _password_field("گذرواژهٔ فعلی")
        self.new_password = _password_field("گذرواژهٔ جدید")
        self.confirm_password = _password_field("تکرار گذرواژهٔ جدید")

        form.addRow(widgets.label("گذرواژهٔ فعلی:"), self.current_password)
        form.addRow(widgets.label("گذرواژهٔ جدید:"), self.new_password)
        form.addRow(widgets.label("تکرار گذرواژهٔ جدید:"), self.confirm_password)
        panel.body.addLayout(form)

        self.password_message = widgets.label("", wrap=True)
        self.password_message.setVisible(False)
        panel.body.addWidget(self.password_message)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.change_password_button = widgets.button(
            "تغییر گذرواژه", icon_name="key", variant="primary", on_click=self._change_password
        )
        self.change_password_button.setEnabled(self.context.can(SETTINGS_CHANGE_OWN_PASSWORD))
        self.change_password_button.setVisible(not is_server_edition())
        buttons.addWidget(self.change_password_button)
        panel.body.addLayout(buttons)
        return panel

    def _build_about_panel(self) -> QWidget:
        panel = widgets.Panel("دربارهٔ برنامه و پرونده‌ها")

        self.about_label = widgets.label("", name="Muted", wrap=True)
        panel.body.addWidget(self.about_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.open_log_button = widgets.button(
            "مشاهده لاگ", icon_name="file", on_click=self._open_log
        )
        self.open_log_button.setEnabled(self.context.can(SETTINGS_VIEW_LOG))
        self.open_data_button = widgets.button(
            "پوشهٔ داده‌های برنامه", icon_name="folder", on_click=self._open_data_folder
        )
        buttons.addWidget(self.open_log_button)
        buttons.addWidget(self.open_data_button)
        buttons.addStretch(1)
        panel.body.addLayout(buttons)

        if not self.context.can(SETTINGS_VIEW_LOG):
            self.open_log_button.setToolTip("نقش شما اجازهٔ مشاهدهٔ لاگ را ندارد")
        return panel

    # ------------------------------------------------------------------ values
    def _reload_values(self) -> None:
        store = self.context.store
        self.base_url_input.setText(store.base_url)
        self.notify_desktop_check.setChecked(bool(store.get_setting("notify_desktop", True)))
        self.notify_sound_check.setChecked(bool(store.get_setting("notify_sound", True)))
        self.close_to_tray_check.setChecked(bool(store.get_setting("close_to_tray", True)))
        self.sazeh_watch_check.setChecked(bool(store.get_setting("sazeh_watch", True)))
        try:
            self.autostart_check.setChecked(autostart.is_enabled())
        except Exception:  # noqa: BLE001 - no registry (not Windows)
            self.autostart_check.setEnabled(False)
        self.poll_spin.setValue(store.get_int_setting("event_poll_seconds", 3, minimum=2,
                                                      maximum=600))
        self.refresh_spin.setValue(self.context.auto_refresh_seconds)
        self.timeout_spin.setValue(self.context.session_timeout_minutes)

        self.about_label.setText(
            "نسخهٔ برنامه: " + to_persian_digits(APP_VERSION)
            + "\n" + "کاربر جاری: " + (self.context.display_name or "—")
            + " (" + role_fa(self.context.role) + ")"
            + "\n" + "پروندهٔ تنظیمات محلی: " + str(db_path())
            + "\n" + "پروندهٔ لاگ: " + str(log_path())
        )
        if self.context.connection_ok:
            self._set_status(
                "ارتباط با سرور فروشگاه برقرار است.", theme.SUCCESS_DARK
            )
            self._apply_system_info()
        elif not self.base_url_input.text():
            self._set_status("آدرس سرور فروشگاه تنظیم نشده است.", theme.WARNING)
        else:
            self._set_status("ارتباط با سرور فروشگاه بررسی نشده است.", theme.TEXT_MUTED)

    def _apply_system_info(self) -> None:
        info = self.context.system_info
        if not self.context.connection_ok:
            return
        if not info.write_mode_known:
            # Older shopapi build: /admin/system-info is missing, so the app
            # cannot know whether writes are real. Say so plainly.
            self._set_status(
                "ارتباط با سرور فروشگاه برقرار است، اما وضعیت ثبت در حسابداری "
                "از این نسخهٔ سرویس خوانده نشد.",
                theme.WARNING_TEXT,
            )
            self.connection_hint.setText(
                "برای نمایش وضعیت ثبت در حسابداری، نرم‌افزار سرور فروشگاه را "
                "روی رایانهٔ سرور به‌روز کنید."
            )
            return
        from .server import write_text

        # v2.8.1: the same plain reason as on «سرور فروشگاه» (not allowed / switched off)
        mode, _color = write_text({
            "accounting_write_enabled": info.accounting_write_enabled,
            "test_mode": info.test_mode,
            "accounting_database": info.accounting_database,
            "status_code_configured": info.status_code_configured,
            "write_block_reason": info.extra.get("write_block_reason"),
        })
        self._set_status(
            f"ارتباط با سرور فروشگاه برقرار است. ثبت در حسابداری: {mode}",
            theme.SUCCESS_DARK if info.accounting_write_enabled else theme.WARNING_TEXT,
        )
        if info.reachable:
            self.connection_hint.setText(
                f"سطح قیمت ربات: {to_persian_digits(info.price_level_bot)} — "
                f"سطح قیمت سایت: {to_persian_digits(info.price_level_site)} — "
                f"مهلت ارسال رسید: {to_persian_digits(info.receipt_deadline_minutes)} دقیقه"
            )

    def _set_status(self, text: str, color: str) -> None:
        self.connection_status.setText(text)
        self.connection_status.setStyleSheet(f"color: {color};")

    # ------------------------------------------------------------------ actions
    def _test_connection(self) -> None:
        self.test_button.setEnabled(False)
        self.test_button.setText("در حال آزمایش…")
        base_url = self.base_url_input.text().strip().rstrip("/")
        if not base_url:
            self.test_button.setEnabled(True)
            self.test_button.setText("آزمایش اتصال")
            widgets.error(self, "آزمایش اتصال", "آدرس سرور فروشگاه را وارد کنید.")
            return

        from ...api_client import ShopApiClient

        same_server = base_url == self.context.store.base_url

        def work():
            if same_server:
                # Our own session also proves the account still works.
                return self.context.api.test_connection()
            if base_url.startswith("https://"):
                from ...api_client import fetch_server_certificate

                pem, _fp = fetch_server_certificate(base_url)
            else:
                pem = ""
            probe = ShopApiClient(base_url, timeout=10, server_cert_pem=pem)
            try:
                return probe.probe_server()
            finally:
                probe.close()

        def ok(result) -> None:
            if same_server:
                self.context.apply_system_info(result)
                self._apply_system_info()
                self.notify_success("ارتباط با سرور فروشگاه با موفقیت برقرار شد")
                if not result.accounting_write_enabled:
                    self.notify_warning(
                        "حالت آزمایشی — سفارش‌ها واقعاً در حسابداری ثبت نمی‌شوند"
                    )
            else:
                self._set_status("سرور در این آدرس پاسخ داد. برای استفاده، آدرس را ذخیره "
                                 "کنید و دوباره وارد شوید.", theme.SUCCESS_DARK)

        def fail(message: str, kind: str) -> None:
            if same_server:
                self.context.mark_offline()
            self._set_status(message, theme.DANGER)
            widgets.error(self, "آزمایش اتصال ناموفق بود", message)

        def done() -> None:
            self.test_button.setEnabled(True)
            self.test_button.setText("آزمایش اتصال")

        run_async(work, on_success=ok, on_error=fail, on_done=done)

    def _show_server_info(self) -> None:
        if not self.context.connection_ok:
            widgets.error(self, "اطلاعات سرور",
                          "ابتدا با دکمهٔ «آزمایش اتصال» ارتباط را برقرار کنید.")
            return
        info = self.context.system_info
        lines = [
            f"ثبت در حسابداری: {'فعال' if info.accounting_write_enabled else 'غیرفعال (حالت آزمایشی)'}",
            f"سطح قیمت ربات: {to_persian_digits(info.price_level_bot)}",
            f"سطح قیمت سایت: {to_persian_digits(info.price_level_site)}",
            f"مهلت ارسال رسید: {to_persian_digits(info.receipt_deadline_minutes)} دقیقه",
            f"پایگاه‌دادهٔ حسابداری: {info.accounting_database or '—'}",
            "کد وضعیت سفارش: " + ("تنظیم شده" if info.status_code_configured
                                   else "تنظیم نشده (ثبت واقعی انجام نمی‌شود)"),
            f"حداکثر تعداد هر قلم: {to_persian_digits(info.max_order_qty)}",
            "اجازهٔ کد شخص مشترک: " + ("بله" if info.allow_shared_person_code else "خیر"),
        ]
        widgets.info(self, "اطلاعات سرور فروشگاه", "\n".join(lines))

    def _save_connection(self) -> None:
        if not self.context.can(SETTINGS_EDIT_CONNECTION):
            widgets.error(self, "دسترسی غیرمجاز",
                          "تغییر تنظیمات اتصال فقط توسط مدیر یا دسترسی «تنظیمات سرور فروشگاه — تغییر» امکان‌پذیر است.")
            return
        base_url = self.base_url_input.text().strip()
        if not base_url.startswith(("http://", "https://")):
            widgets.error(self, "آدرس نامعتبر",
                          "آدرس سرور باید با http:// یا https:// شروع شود.")
            return
        base_url = base_url.rstrip("/")
        if base_url == self.context.store.base_url:
            self.notify_success("آدرس سرور تغییری نکرد")
            return
        if not widgets.confirm(
            self, "تغییر آدرس سرور",
            "پس از تغییر آدرس، از حساب خارج می‌شوید، اثرانگشت امنیتی سرور جدید را تأیید "
            "می‌کنید و سپس روی آن وارد می‌شوید. ادامه می‌دهید؟",
            confirm_text="تغییر و خروج", cancel_text="انصراف",
        ):
            return
        self.context.audit("settings_connection", f"base_url={base_url}")
        log.info("server address changed to %s", base_url)
        # Saved first; the API client still points at the OLD server, so the
        # logout below ends the session there before the login window switches
        # to the new address.
        # A new server means a new certificate to verify: the setup wizard runs
        # again (with this address filled in) after signing out.
        self.context.store.configure_connection(base_url, "")
        self.context.store.set_setting("wizard_completed", False)
        window = self.window()
        if hasattr(window, "logout_requested"):
            window.logout_requested.emit()
        else:
            self.context.api.configure(base_url)

    def _save_general(self) -> None:
        if not self.context.can(SETTINGS_EDIT_GENERAL):
            widgets.error(self, "دسترسی غیرمجاز", "تغییر این تنظیمات برای نقش شما مجاز نیست.")
            return
        self.context.store.set_setting("auto_refresh_seconds", int(self.refresh_spin.value()))
        self.context.store.set_setting("session_timeout_minutes", int(self.timeout_spin.value()))
        self.context.audit("settings_general", "بازه‌های زمانی به‌روزرسانی شد")
        self.notify_success("تنظیمات ذخیره شد")
        window = self.window()
        if hasattr(window, "apply_settings_changed"):
            window.apply_settings_changed()

    def _save_notifications(self) -> None:
        store = self.context.store
        store.set_setting("notify_desktop", self.notify_desktop_check.isChecked())
        store.set_setting("notify_sound", self.notify_sound_check.isChecked())
        store.set_setting("close_to_tray", self.close_to_tray_check.isChecked())
        store.set_setting("sazeh_watch", self.sazeh_watch_check.isChecked())
        if self.autostart_check.isEnabled():
            try:
                autostart.set_enabled(self.autostart_check.isChecked())
            except OSError:
                self.notify_error("تنظیم اجرای خودکار در ویندوز ممکن نشد")
        store.set_setting("event_poll_seconds", int(self.poll_spin.value()))
        self.notify_success("تنظیمات اعلان ذخیره شد")

    def _change_password(self) -> None:
        current = self.current_password.text()
        new = self.new_password.text()
        confirm = self.confirm_password.text()
        self.change_password_button.setEnabled(False)

        def work() -> None:
            self.context.auth.change_own_password(current, new, confirm)

        def ok(_result) -> None:
            self._show_password_message(
                "گذرواژه با موفقیت تغییر کرد. نشست‌های دیگر شما روی سایر رایانه‌ها بسته شد.",
                ok=True)
            for field in (self.current_password, self.new_password, self.confirm_password):
                field.clear()
            self.notify_success("گذرواژه با موفقیت تغییر کرد")

        def done() -> None:
            self.change_password_button.setEnabled(self.context.can(SETTINGS_CHANGE_OWN_PASSWORD))

        run_async(work, on_success=ok,
                  on_error=lambda m, _k: self._show_password_message(m, ok=False),
                  on_done=done)

    def _show_password_message(self, text: str, *, ok: bool) -> None:
        self.password_message.setText(text)
        self.password_message.setStyleSheet(
            f"color: {theme.SUCCESS_DARK if ok else theme.DANGER};"
        )
        self.password_message.setVisible(True)

    def _open_log(self) -> None:
        path = log_path()
        if not path.exists():
            widgets.info(self, "مشاهده لاگ",
                         "هنوز فایل لاگی ساخته نشده است.")
            return
        _open_path(path)

    def _open_data_folder(self) -> None:
        _open_path(data_dir(), folder=True)


def _password_field(placeholder: str) -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setPlaceholderText(placeholder)
    field.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    return field


def _open_path(path: Path, folder: bool = False) -> bool:
    """Open a file or folder with the OS default handler."""
    try:
        if folder:
            os.startfile(str(path))  # noqa: S606 - Windows shell open
        else:
            os.startfile(str(path))  # noqa: S606
        return True
    except (OSError, AttributeError):
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
