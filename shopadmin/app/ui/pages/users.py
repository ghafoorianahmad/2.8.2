"""صفحهٔ کاربران سیستم — حساب کارکنان فروشگاه روی سرور (فقط مدیر کل).

حساب‌ها، نقش‌ها و گذرواژه‌ها روی سرور نگه داشته و همان‌جا کنترل می‌شوند؛ این
صفحه فقط آن‌ها را از طریق API مدیریت می‌کند. این کاربران با مشتریان فرق دارند.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ...auth import MIN_PASSWORD_LENGTH, validate_password_strength
from ...permissions import USERS_MANAGE, USERS_VIEW
from ...persian import format_shamsi, normalize_fa, to_persian_digits
from ...statuses import ALL_ROLES, ROLE_DESCRIPTION_FA, ROLE_SUPER_ADMIN, role_fa
from .. import theme, widgets
from ..async_utils import run_async
from ..base_page import BasePage

HEADERS = ("نام کاربری", "نام و نام خانوادگی", "نقش", "وضعیت", "آخرین ورود", "تاریخ ایجاد", "عملیات")


class UsersPage(BasePage):
    title = "کاربران سیستم"
    subtitle = "حساب کارکنان فروشگاه روی سرور — فقط مدیر کل"

    def build_body(self) -> None:
        if not self.context.can(USERS_VIEW):
            self.body.addWidget(_forbidden_panel())
            return

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = widgets.SearchBox("جستجوی نام کاربری یا نام…")
        self.search.textChanged.connect(lambda _t: self._render())
        bar.addWidget(self.search)
        bar.addStretch(1)
        self.add_button = widgets.button(
            "کاربر جدید", icon_name="plus", variant="primary", on_click=self._create_user
        )
        self.add_button.setEnabled(self.context.can(USERS_MANAGE))
        bar.addWidget(self.add_button)
        self.body.addLayout(bar)

        panel = widgets.Panel("فهرست کارکنان")
        panel.body.addWidget(widgets.label(
            "هر کارمند با این حساب از هر رایانهٔ فروشگاه وارد برنامه می‌شود. دسترسی‌ها "
            "روی سرور کنترل می‌شوند؛ تغییر نقش، غیرفعال کردن یا تغییر گذرواژه، کاربر را "
            "فوراً از همهٔ رایانه‌ها خارج می‌کند.",
            name="Muted", wrap=True,
        ))
        self.table = widgets.DataTable(HEADERS, key="users")
        self.table.set_empty_state("کاربری ثبت نشده است", "", "users")
        self.table.setMinimumHeight(340)
        panel.body.addWidget(self.table, 1)
        self.summary = widgets.label("", name="Muted")
        panel.body.addWidget(self.summary)
        self.body.addWidget(panel, 1)

        self._users: list[dict] = []

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        if not self.context.can(USERS_VIEW):
            return
        self.run(self.context.auth.list_users, on_success=self._loaded)

    def _loaded(self, users: list) -> None:
        self._users = list(users or [])
        self._render()

    def _render(self) -> None:
        needle = normalize_fa(self.search.text()) if hasattr(self, "search") else ""
        users = [
            user for user in self._users
            if not needle
            or needle in normalize_fa(user.get("username", ""))
            or needle in normalize_fa(user.get("full_name", ""))
        ]

        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for user in users:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.set_cell(row, 0, str(user.get("username") or "—"), bold=True)
                self.table.set_cell(row, 1, str(user.get("full_name") or "—"))
                self.table.set_widget(row, 2, widgets.pill_cell(
                    _role_pill(str(user.get("role")))
                ))
                self.table.set_widget(row, 3, widgets.pill_cell(_state_pill(user)))
                self.table.set_cell(
                    row, 4,
                    format_shamsi(user.get("last_login_at")) if user.get("last_login_at") else "—",
                )
                self.table.set_cell(row, 5, format_shamsi(user.get("created_at")))
                self.table.set_widget(row, 6, self._actions_for(user))
        finally:
            self.table.setUpdatesEnabled(True)
        self.table._refresh_states()

        active_count = sum(1 for u in self._users if u.get("active"))
        self.summary.setText(
            f"{to_persian_digits(len(users))} کاربر نمایش داده شد — "
            f"{to_persian_digits(active_count)} کاربر فعال از "
            f"{to_persian_digits(len(self._users))} کاربر"
        )
        if not users:
            self.table.set_empty_state(
                "کاربری با این جستجو پیدا نشد" if needle else "هنوز کاربری ساخته نشده است",
                "با دکمهٔ «کاربر جدید» یک کاربر داخلی بسازید." if not needle else
                "عبارت جستجو را تغییر دهید.",
                "search" if needle else "users",
            )
            self.table._refresh_states()

    # ------------------------------------------------------------------ actions
    def _actions_for(self, user: dict) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        can_manage = self.context.can(USERS_MANAGE)
        is_self = self.context.principal and int(user["id"]) == int(self.context.principal.user_id)

        edit = widgets.button("ویرایش", icon_name="edit",
                              on_click=lambda u=user: self._edit_user(u))
        edit.setEnabled(can_manage)
        layout.addWidget(edit)

        reset = widgets.button("تغییر گذرواژه", icon_name="key",
                               on_click=lambda u=user: self._reset_password(u))
        reset.setEnabled(can_manage)
        layout.addWidget(reset)

        default = widgets.button("بازنشانی به ۱۲۳۴۵", icon_name="key",
                                 on_click=lambda u=user: self._reset_default(u),
                                 tooltip="گذرواژه ۱۲۳۴۵ می‌شود و کاربر در ورود بعدی باید عوضش کند")
        default.setEnabled(can_manage)
        layout.addWidget(default)

        if user.get("locked"):
            unlock = widgets.button("رفع قفل", icon_name="key",
                                    on_click=lambda u=user: self._unlock(u))
            unlock.setEnabled(can_manage)
            layout.addWidget(unlock)

        active = bool(user.get("active"))
        toggle = widgets.button(
            "غیرفعال" if active else "فعال‌سازی",
            variant="ghost",
            on_click=lambda u=user: self._toggle_active(u),
        )
        toggle.setEnabled(can_manage and not is_self)
        if is_self:
            toggle.setToolTip("نمی‌توانید حساب خودتان را غیرفعال کنید")
        layout.addWidget(toggle)

        delete = widgets.button("حذف", variant="danger",
                                on_click=lambda u=user: self._delete_user(u))
        delete.setEnabled(can_manage and not is_self)
        if is_self:
            delete.setToolTip("نمی‌توانید حساب خودتان را حذف کنید")
        layout.addWidget(delete)

        layout.addStretch(1)
        return holder

    def _create_user(self) -> None:
        if not self._manage_allowed():
            return
        dialog = UserFormDialog(self.context, None, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.notify_success(f"کاربر «{dialog.result_username}» با موفقیت ساخته شد")
        self.load()

    def _edit_user(self, user: dict) -> None:
        if not self._manage_allowed():
            return
        dialog = UserFormDialog(self.context, user, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.notify_success("اطلاعات کاربر ذخیره شد")
        self.load()

    def _reset_password(self, user: dict) -> None:
        if not self._manage_allowed():
            return
        dialog = ResetPasswordDialog(self, str(user.get("username") or ""))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        user_id, password = int(user["id"]), dialog.new_password
        must_change = dialog.must_change
        self.run(
            lambda: self.context.auth.reset_password(user_id, password,
                                                     must_change_password=must_change),
            on_success=lambda _r: (self.notify_success(
                "گذرواژهٔ جدید تعیین شد؛ کاربر در ورود بعدی باید آن را عوض کند" if must_change
                else "گذرواژهٔ جدید تعیین شد"), self.load()),
            on_error=lambda m, _k: widgets.error(self, "تغییر گذرواژه انجام نشد", m),
        )

    def _reset_default(self, user: dict) -> None:
        if not self._manage_allowed():
            return
        name = str(user.get("username") or "")
        if not widgets.confirm(
            self, "بازنشانی گذرواژه",
            f"گذرواژهٔ «{name}» به ۱۲۳۴۵ برگردانده شود؟",
            confirm_text="بازنشانی", kind="warning",
            detail="کاربر از همهٔ رایانه‌ها خارج می‌شود و در ورود بعدی فقط می‌تواند گذرواژهٔ "
                   "تازه انتخاب کند.",
        ):
            return
        user_id = int(user["id"])
        self.run(
            lambda: self.context.auth.reset_password_to_default(user_id),
            on_success=lambda _r: (self.notify_success(
                "گذرواژه ۱۲۳۴۵ شد؛ کاربر در ورود بعدی باید آن را عوض کند"), self.load()),
            on_error=lambda m, _k: widgets.error(self, "بازنشانی انجام نشد", m),
        )

    def _unlock(self, user: dict) -> None:
        if not self._manage_allowed():
            return
        user_id = int(user["id"])
        self.run(
            lambda: self.context.auth.unlock_user(user_id),
            on_success=lambda _r: (self.notify_success("قفل حساب برداشته شد"), self.load()),
            on_error=lambda m, _k: widgets.error(self, "رفع قفل انجام نشد", m),
        )

    def _toggle_active(self, user: dict) -> None:
        if not self._manage_allowed():
            return
        active = bool(user.get("active"))
        name = str(user.get("username") or "")
        if not widgets.confirm(
            self,
            "غیرفعال کردن کاربر" if active else "فعال‌سازی کاربر",
            f"آیا از {'غیرفعال کردن' if active else 'فعال کردن'} کاربر «{name}» مطمئن هستید؟",
            confirm_text="غیرفعال کن" if active else "فعال کن",
            kind="warning" if active else "question",
        ):
            return
        user_id, actor_id = int(user["id"]), self.context.principal.user_id
        self.run(
            lambda: self.context.auth.update_user(user_id, is_active=not active,
                                                  actor_id=actor_id),
            on_success=lambda _r: (self.notify_success("وضعیت کاربر تغییر کرد"), self.load()),
            on_error=lambda m, _k: widgets.error(self, "تغییر وضعیت انجام نشد", m),
        )

    def _delete_user(self, user: dict) -> None:
        if not self._manage_allowed():
            return
        name = str(user.get("username") or "")
        if not widgets.confirm(
            self, "حذف کاربر",
            f"آیا از حذف کاربر «{name}» مطمئن هستید؟ این کار قابل بازگشت نیست.",
            confirm_text="حذف کن", kind="danger",
            detail="برای جلوگیری از حذف تصادفی، عملیات فقط پس از تأیید انجام می‌شود.",
        ):
            return
        user_id = int(user["id"])
        self.run(
            lambda: self.context.auth.delete_user(user_id),
            on_success=lambda _r: (self.notify_success("کاربر حذف شد"), self.load()),
            on_error=lambda m, _k: widgets.error(self, "حذف کاربر انجام نشد", m),
        )

    def _manage_allowed(self) -> bool:
        if self.context.can(USERS_MANAGE):
            return True
        widgets.error(self, "دسترسی غیرمجاز",
                      "مدیریت کاربران سیستم فقط برای نقش «مدیر کل» مجاز است.")
        return False


def _role_pill(role: str) -> widgets.StatusPill:
    colors = {
        ROLE_SUPER_ADMIN: theme.ROLE_PURPLE,
        "admin": theme.PRIMARY_DARK,
        "operator": theme.INFO_DARK,
        "viewer": theme.TEXT_MUTED,
    }
    backgrounds = {
        ROLE_SUPER_ADMIN: theme.SURFACE,
        "admin": theme.PRIMARY_LIGHT,
        "operator": theme.INFO_LIGHT,
        "viewer": theme.BACKGROUND,
    }
    pill = widgets.StatusPill(role_fa(role))
    color = colors.get(role, theme.TEXT_MUTED)
    background = backgrounds.get(role, theme.BACKGROUND)
    pill.setStyleSheet(
        f"color: {color}; background: {background}; border: 1px solid {color}44; "
        f"border-radius: 10px; padding: 4px 10px; font-weight: 600;"
    )
    return pill


def _state_pill(user: dict) -> widgets.StatusPill:
    if not user.get("active"):
        return widgets.StatusPill("غیرفعال", "rejected")
    if user.get("locked"):
        return widgets.StatusPill("قفل موقت", "expired")
    if user.get("must_change_password"):
        return widgets.StatusPill("گذرواژهٔ موقت", "awaiting_payment")
    return widgets.StatusPill("فعال", "approved")


def _forbidden_panel() -> QWidget:
    panel = widgets.Panel()
    panel.body.addWidget(widgets.label("دسترسی غیرمجاز", size=14, bold=True))
    panel.body.addWidget(widgets.label(
        "مدیریت کاربران سیستم فقط برای نقش «مدیر کل» در دسترس است.",
        name="Muted", wrap=True,
    ))
    return panel


# --------------------------------------------------------------------------
# dialogs
# --------------------------------------------------------------------------
class UserFormDialog(QDialog):
    """ساخت یا ویرایش حساب یک کارمند روی سرور."""

    def __init__(self, context, user: Optional[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.user = user
        self.editing = user is not None
        self.result_username = ""

        self.setWindowTitle("ویرایش کاربر" if self.editing else "کاربر جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(widgets.label(
            "ویرایش حساب کارمند" if self.editing else "حساب کارمند جدید", size=14, bold=True
        ))
        root.addWidget(widgets.label(
            "این حساب روی سرور فروشگاه ساخته می‌شود و کارمند با آن از هر رایانه‌ای وارد "
            "برنامهٔ مدیریت می‌شود (نه حساب مشتری).",
            name="Muted", wrap=True,
        ))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self.username_input = QLineEdit()
        self.username_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.username_input.setPlaceholderText("مثلاً: operator1")
        self.full_name_input = QLineEdit()
        self.full_name_input.setPlaceholderText("مثلاً: علی رضایی")
        self.role_combo = QComboBox()
        for role in ALL_ROLES:
            self.role_combo.addItem(role_fa(role), role)
        self.role_hint = widgets.label("", name="Muted", wrap=True)
        self.role_combo.currentIndexChanged.connect(self._update_role_hint)

        if self.editing:
            self.username_input.setText(str(user.get("username") or ""))
            self.username_input.setEnabled(False)
            self.username_input.setToolTip("نام کاربری پس از ساخت قابل تغییر نیست")
            self.full_name_input.setText(str(user.get("full_name") or ""))
            index = self.role_combo.findData(user.get("role"))
            self.role_combo.setCurrentIndex(max(0, index))

        form.addRow(widgets.label("نام کاربری:"), self.username_input)
        form.addRow(widgets.label("نام و نام خانوادگی:"), self.full_name_input)
        form.addRow(widgets.label("نقش:"), self.role_combo)
        form.addRow(widgets.label(""), self.role_hint)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.password_input.setPlaceholderText(
            f"حداقل {to_persian_digits(MIN_PASSWORD_LENGTH)} نویسه، حرف و عدد")
        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        if not self.editing:
            form.addRow(widgets.label("گذرواژه:"), self.password_input)
            form.addRow(widgets.label("تکرار گذرواژه:"), self.confirm_input)

        self.active_check = QCheckBox("این کاربر فعال باشد")
        self.active_check.setChecked(bool(user.get("active", True)) if self.editing else True)
        form.addRow(widgets.label("وضعیت:"), self.active_check)

        self.must_change_check = QCheckBox("در اولین ورود، گذرواژه را خودش عوض کند (توصیه می‌شود)")
        self.must_change_check.setChecked(True)
        if not self.editing:
            form.addRow(widgets.label(""), self.must_change_check)

        root.addLayout(form)

        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = widgets.button(
            "ذخیره", variant="primary", icon_name="save", on_click=self._submit
        )
        self.save_button = save
        cancel = widgets.button("انصراف", on_click=self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

        self._update_role_hint()

    def _update_role_hint(self) -> None:
        role = self.role_combo.currentData()
        self.role_hint.setText(ROLE_DESCRIPTION_FA.get(str(role), ""))

    def _fail(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _submit(self) -> None:
        if not self.save_button.isEnabled():
            return
        auth = self.context.auth
        role = str(self.role_combo.currentData())
        full_name = self.full_name_input.text().strip()
        active = self.active_check.isChecked()
        actor_id = self.context.principal.user_id

        if self.editing:
            user_id = int(self.user["id"])
            self.result_username = str(self.user.get("username") or "")

            def work():
                return auth.update_user(user_id, full_name=full_name, role=role,
                                        is_active=active, actor_id=actor_id)
        else:
            username = self.username_input.text().strip()
            password = self.password_input.text()
            if password != self.confirm_input.text():
                self._fail("تکرار گذرواژه با گذرواژهٔ جدید یکسان نیست.")
                return
            problem = validate_password_strength(password)
            if problem:
                self._fail(problem)
                return
            must_change = self.must_change_check.isChecked()

            def work():
                created = auth.create_user(username, full_name, password, role,
                                           must_change_password=must_change)
                if not active:
                    auth.update_user(created.user_id, is_active=False)
                return created

        def ok(result) -> None:
            if not self.editing:
                self.result_username = result.username
            self.accept()

        def done() -> None:
            self.save_button.setEnabled(True)

        self.error_label.setVisible(False)
        self.save_button.setEnabled(False)
        run_async(work, on_success=ok, on_error=lambda m, _k: self._fail(m), on_done=done)


class ResetPasswordDialog(QDialog):
    """تعیین گذرواژهٔ موقت برای یک کارمند توسط مدیر کل."""

    def __init__(self, parent: QWidget | None, username: str) -> None:
        super().__init__(parent)
        self.new_password = ""
        self.must_change = True
        self.setWindowTitle("تغییر گذرواژهٔ کاربر")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(widgets.label("تغییر گذرواژهٔ کاربر", size=14, bold=True))
        root.addWidget(widgets.label(
            f"گذرواژهٔ جدید «{username}» را تعیین کنید. او از همهٔ رایانه‌ها خارج می‌شود. "
            "گذرواژه به‌صورت رمزنگاری‌شده ذخیره می‌شود و بعداً قابل نمایش نیست.", wrap=True
        ))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        form.addRow(widgets.label("گذرواژهٔ جدید:"), self.password_input)
        form.addRow(widgets.label("تکرار گذرواژه:"), self.confirm_input)
        root.addLayout(form)
        self.must_change_check = QCheckBox("کاربر در ورود بعدی گذرواژه را خودش عوض کند (توصیه می‌شود)")
        self.must_change_check.setChecked(True)
        root.addWidget(self.must_change_check)

        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(widgets.button("ذخیره", variant="primary", on_click=self._submit))
        buttons.addWidget(widgets.button("انصراف", on_click=self.reject))
        root.addLayout(buttons)

    def _submit(self) -> None:
        password = self.password_input.text()
        if password != self.confirm_input.text():
            self.error_label.setText("تکرار گذرواژه یکسان نیست.")
            self.error_label.setVisible(True)
            return
        problem = validate_password_strength(password)
        if problem:
            self.error_label.setText(problem)
            self.error_label.setVisible(True)
            return
        self.new_password = password
        self.must_change = self.must_change_check.isChecked()
        self.accept()
