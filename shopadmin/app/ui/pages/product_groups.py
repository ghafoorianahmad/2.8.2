"""صفحهٔ «گروه‌های کالا» (نسخهٔ ۲٫۶٫۰).

گروه‌های کالای «سازه حساب» با دو تیک برای هر گروه:

* «نمایش در ربات» — فقط کالاهای گروه‌های تیک‌خورده به مشتری نشان داده و فروخته می‌شوند؛
  تا هیچ گروهی انتخاب نشود ربات هیچ کالایی نشان نمی‌دهد.
* «گروه گوشی» — کالای این گروه‌ها گوشی است: فقط وقتی در لیست قیمت معتبر فعلی هست
  نمایش داده و فروخته می‌شود، قیمتش فقط از همان لیست است و پنجرهٔ فروش گوشی
  (بسته بودن فروش) رویش اعمال می‌شود.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QWidget

from ...permissions import CATALOG_MANAGE
from ...persian import to_persian_digits
from .. import theme, widgets
from ..base_page import BasePage

HEADERS = ("کد گروه", "نام گروه", "نمایش در ربات", "گروه گوشی")


def _centered(check: QCheckBox) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(4, 0, 4, 0)
    layout.addStretch(1)
    layout.addWidget(check)
    layout.addStretch(1)
    return holder


class ProductGroupsPage(BasePage):
    title = "گروه‌های کالا"
    subtitle = "کدام گروه‌ها در ربات دیده شوند و کدام گروه‌ها گوشی هستند"

    def build_body(self) -> None:
        self._groups: list[dict] = []
        self._checks: dict[int, tuple[QCheckBox, QCheckBox]] = {}
        self._dirty = False

        panel = widgets.Panel("گروه‌های «سازه حساب»")
        panel.body.addWidget(widgets.label(
            "فقط کالاهای گروه‌های «نمایش در ربات» به مشتری نشان داده و فروخته می‌شوند. "
            "کالای «گروه گوشی» فقط وقتی در لیست قیمت معتبرِ فعلی باشد نمایش داده می‌شود، "
            "قیمتش فقط از لیست است و وقتی فروش گوشی بسته است سفارش داده نمی‌شود.",
            name="Muted", wrap=True))
        self.warning = widgets.label("", color=theme.WARNING_TEXT, bold=True, wrap=True)
        self.warning.setVisible(False)
        panel.body.addWidget(self.warning)
        self.table = widgets.DataTable(HEADERS, key="product_groups")
        self.table.set_empty_state("گروهی دریافت نشد", "اتصال به سرور فروشگاه را بررسی کنید.",
                                   "products")
        self.table.setMinimumHeight(320)
        panel.body.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.summary = widgets.label("", name="Muted")
        bottom.addWidget(self.summary, 1)
        self.save_button = widgets.button("ذخیرهٔ تغییرات", variant="primary", icon_name="check",
                                          on_click=self.save)
        self.save_button.setEnabled(False)
        can_manage = self.context.can(CATALOG_MANAGE)
        self.save_button.setVisible(can_manage)
        bottom.addWidget(self.save_button)
        panel.body.addLayout(bottom)
        self.body.addWidget(panel, 1)

    def load(self) -> None:
        self.run(self.context.api.product_groups, on_success=self._loaded,
                 on_error=lambda m, _k: self.show_table_error(m))

    def _loaded(self, groups: list) -> None:
        self._groups = [g for g in (groups or []) if isinstance(g, dict)]
        self._checks = {}
        editable = self.context.can(CATALOG_MANAGE)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for group in self._groups:
                code = int(group.get("code") or 0)
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.set_cell(row, 0, to_persian_digits(code))
                name = str(group.get("name") or "")
                if group.get("missing"):
                    self.table.set_cell(row, 1, "(در حسابداری نیست)", color=theme.DANGER)
                else:
                    self.table.set_cell(row, 1, name or "—", bold=True)
                shown = QCheckBox()
                shown.setChecked(bool(group.get("show_in_bot")))
                phone = QCheckBox()
                phone.setChecked(bool(group.get("is_phone")))
                for check in (shown, phone):
                    check.setEnabled(editable)
                    check.setCursor(Qt.CursorShape.PointingHandCursor)
                    check.toggled.connect(self._changed)
                shown.setAccessibleName(f"نمایش گروه {name} در ربات")
                phone.setAccessibleName(f"گروه گوشی {name}")
                self.table.set_widget(row, 2, _centered(shown))
                self.table.set_widget(row, 3, _centered(phone))
                self._checks[code] = (shown, phone)
        finally:
            self.table.setUpdatesEnabled(True)
        self.table._refresh_states()
        self._dirty = False
        self.save_button.setEnabled(False)
        self._update_summary()

    def values(self) -> list[dict]:
        return [{"code": code, "show_in_bot": shown.isChecked(), "is_phone": phone.isChecked()}
                for code, (shown, phone) in self._checks.items()]

    def _changed(self, _checked: bool = False) -> None:
        self._dirty = True
        self.save_button.setEnabled(self.context.can(CATALOG_MANAGE))
        self._update_summary()

    def _update_summary(self) -> None:
        values = self.values()
        shown = sum(1 for v in values if v["show_in_bot"])
        phones = sum(1 for v in values if v["is_phone"])
        self.summary.setText(
            f"{to_persian_digits(len(values))} گروه — {to_persian_digits(shown)} در ربات، "
            f"{to_persian_digits(phones)} گروه گوشی" + ("  (ذخیره نشده)" if self._dirty else ""))
        if values and not shown:
            self.warning.setText("هیچ گروهی برای نمایش در ربات انتخاب نشده؛ ربات هیچ کالایی "
                                 "به مشتری نشان نمی‌دهد.")
            self.warning.setVisible(True)
        elif values and not phones:
            self.warning.setText("هیچ «گروه گوشی» انتخاب نشده؛ گوشی‌ها مثل لوازم جانبی با قیمت "
                                 "حسابداری فروخته می‌شوند و بسته بودن فروش گوشی رویشان اثر ندارد.")
            self.warning.setVisible(True)
        else:
            self.warning.setVisible(False)

    def save(self) -> None:
        if not self.context.can(CATALOG_MANAGE):
            return
        values = self.values()
        self.run(lambda: self.context.api.save_product_groups(values),
                 on_success=self._saved,
                 on_error=lambda m, _k: widgets.error(self, "ذخیره نشد", m))

    def _saved(self, groups: list) -> None:
        self.notify_success("گروه‌های کالا ذخیره شد؛ ربات از همین حالا با تنظیم جدید کار می‌کند.")
        self._loaded(groups)
