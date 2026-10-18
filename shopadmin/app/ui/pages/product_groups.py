"""صفحهٔ «گروه‌های کالا» (نسخهٔ ۲٫۶٫۰، درختی از نسخهٔ ۲٫۶٫۱).

گروه‌های کالای «سازه حساب» به‌صورت درخت (مثلاً «گوشی» و زیرگروه هر برند) با سه تیک:

* «نمایش در ربات» — فقط کالاهای گروه‌های تیک‌خورده به مشتری نشان داده و فروخته می‌شوند؛
  تا هیچ گروهی انتخاب نشود ربات هیچ کالایی نشان نمی‌دهد.
* «گروه گوشی» — کالای این گروه‌ها گوشی است: فقط وقتی در لیست قیمت معتبر فعلی هست
  نمایش داده و فروخته می‌شود، قیمتش فقط از همان لیست است و پنجرهٔ فروش گوشی
  (بسته بودن فروش) رویش اعمال می‌شود.
* «قیمت با استعلام» — کالا بدون قیمت نشان داده می‌شود و به سبد نمی‌رود؛ مشتری
  «استعلام قیمت» می‌زند و درخواست در صفحهٔ «درخواست کالا» می‌آید.

تیک گروه والد به همهٔ زیرگروه‌هایش می‌رسد (سرور هم در همهٔ بررسی‌ها همین ارث را
اعمال می‌کند)؛ تیک به‌ارث‌رسیده خاکستری است و تا تیک والد برداشته نشود عوض نمی‌شود.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ...permissions import CATALOG_MANAGE
from ...persian import to_persian_digits
from .. import theme, widgets
from ..base_page import BasePage

#: (key, column title) of the three per-group checkboxes.
FLAGS = (("show_in_bot", "نمایش در ربات"), ("is_phone", "گروه گوشی"),
         ("price_on_inquiry", "قیمت با استعلام"))
HEADERS = ("نام گروه", "کد گروه") + tuple(title for _, title in FLAGS)
FLAG_COLUMN = {key: 2 + i for i, (key, _) in enumerate(FLAGS)}
INHERITED_TIP = "از گروه بالاتر به ارث رسیده؛ برای تغییر، تیک گروه والد را بردارید."


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
    subtitle = "کدام گروه‌ها در ربات دیده شوند، کدام گوشی‌اند و کدام قیمت با استعلام دارند"
    help_text = "مشخص کنید کدام گروه‌ها در ربات دیده شوند، کدام گوشی‌اند و قیمت کدام با استعلام است."

    def build_body(self) -> None:
        self._groups: dict[int, dict] = {}
        self._parents: dict[int, int | None] = {}
        self._own: dict[int, dict[str, bool]] = {}
        self._checks: dict[int, dict[str, QCheckBox]] = {}
        self._items: dict[int, QTreeWidgetItem] = {}
        self._dirty = False
        self._loading = False

        panel = widgets.Panel("گروه‌های «سازه حساب»")
        panel.body.addWidget(widgets.label(
            "فقط کالاهای گروه‌های «نمایش در ربات» به مشتری نشان داده و فروخته می‌شوند. "
            "کالای «گروه گوشی» فقط وقتی در لیست قیمت معتبرِ فعلی باشد نمایش داده می‌شود، "
            "قیمتش فقط از لیست است و وقتی فروش گوشی بسته است سفارش داده نمی‌شود. "
            "کالای «قیمت با استعلام» بدون قیمت نشان داده می‌شود و مشتری فقط استعلام می‌فرستد. "
            "تیک هر گروه به همهٔ زیرگروه‌هایش (مثلاً برندهای گوشی) می‌رسد.",
            name="Muted", wrap=True))
        self.warning = widgets.label("", color=theme.WARNING_TEXT, bold=True, wrap=True)
        self.warning.setVisible(False)
        panel.body.addWidget(self.warning)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(HEADERS))
        self.tree.setHeaderLabels(list(HEADERS))
        self.tree.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumHeight(320)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(HEADERS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        panel.body.addWidget(self.tree, 1)
        self.empty = widgets.label("گروهی دریافت نشد؛ اتصال به سرور فروشگاه را بررسی کنید.",
                                   name="Muted", wrap=True)
        self.empty.setVisible(False)
        panel.body.addWidget(self.empty)

        bottom = QHBoxLayout()
        self.summary = widgets.label("", name="Muted")
        bottom.addWidget(self.summary, 1)
        self.save_button = widgets.button("ذخیرهٔ تغییرات", variant="primary", icon_name="check",
                                          on_click=self.save)
        self.save_button.setEnabled(False)
        self.save_button.setVisible(self.context.can(CATALOG_MANAGE))
        bottom.addWidget(self.save_button)
        panel.body.addLayout(bottom)
        self.body.addWidget(panel, 1)

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        self.run(self.context.api.product_groups, on_success=self._loaded,
                 on_error=lambda m, _k: self._failed(m))

    def _failed(self, message: str) -> None:
        self.empty.setText(message or "گروه‌ها دریافت نشد.")
        self.empty.setVisible(True)

    def _loaded(self, groups: list) -> None:
        rows = [g for g in (groups or []) if isinstance(g, dict) and g.get("code") is not None]
        self._groups = {int(g["code"]): g for g in rows}
        self._parents = {}
        for code, g in self._groups.items():
            parent = g.get("parent")
            self._parents[code] = int(parent) if parent is not None \
                and int(parent) in self._groups and int(parent) != code else None
        self._own = {code: {key: bool(g.get(key)) for key, _ in FLAGS}
                     for code, g in self._groups.items()}
        self._build_tree()
        self._dirty = False
        self.save_button.setEnabled(False)
        self._apply_inheritance()
        self.empty.setVisible(not self._groups)
        self._update_summary()

    def _children(self, parent: int | None) -> list[int]:
        return [c for c, p in self._parents.items() if p == parent]

    def _build_tree(self) -> None:
        editable = self.context.can(CATALOG_MANAGE)
        self._loading = True
        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            self._items, self._checks = {}, {}
            placed: set[int] = set()

            def add(code: int, parent_item) -> None:
                if code in placed:          # a cycle in the accounting data: show once
                    return
                placed.add(code)
                group = self._groups[code]
                item = QTreeWidgetItem(parent_item) if parent_item is not None \
                    else QTreeWidgetItem(self.tree)
                name = str(group.get("name") or "").strip()
                if group.get("missing"):
                    item.setText(0, "(در حسابداری نیست)")
                    item.setForeground(0, theme_color(theme.DANGER))
                else:
                    item.setText(0, name or "—")
                item.setText(1, to_persian_digits(code))
                self._items[code] = item
                self._checks[code] = {}
                for key, title in FLAGS:
                    check = QCheckBox()
                    check.setChecked(self._own[code][key])
                    check.setEnabled(editable)
                    check.setCursor(Qt.CursorShape.PointingHandCursor)
                    check.setAccessibleName(f"{title} — {name}")
                    check.toggled.connect(lambda on, c=code, k=key: self._toggled(c, k, on))
                    self.tree.setItemWidget(item, FLAG_COLUMN[key], _centered(check))
                    self._checks[code][key] = check
                for child in sorted(self._children(code)):
                    add(child, item)

            for code in sorted(self._children(None)):
                add(code, None)
            for code in sorted(self._groups):      # anything left (a cycle)
                add(code, None)
            self.tree.expandAll()
        finally:
            self.tree.setUpdatesEnabled(True)
            self._loading = False

    # ------------------------------------------------------------------ inheritance
    def ancestors(self, code: int) -> list[int]:
        out: list[int] = []
        parent = self._parents.get(code)
        while parent is not None and parent not in out and parent != code:
            out.append(parent)
            parent = self._parents.get(parent)
        return out

    def inherited(self, code: int, key: str) -> bool:
        return any(self._own.get(a, {}).get(key) for a in self.ancestors(code))

    def effective(self, code: int, key: str) -> bool:
        return bool(self._own.get(code, {}).get(key)) or self.inherited(code, key)

    def _apply_inheritance(self) -> None:
        """A ticked parent shows its ticks on every subgroup (greyed, not editable)."""
        editable = self.context.can(CATALOG_MANAGE)
        self._loading = True
        try:
            for code, checks in self._checks.items():
                for key, check in checks.items():
                    inherited = self.inherited(code, key)
                    check.setChecked(True if inherited else self._own[code][key])
                    check.setEnabled(editable and not inherited)
                    check.setToolTip(INHERITED_TIP if inherited else "")
        finally:
            self._loading = False

    def _toggled(self, code: int, key: str, checked: bool) -> None:
        if self._loading:
            return
        self._own[code][key] = bool(checked)
        self._dirty = True
        self.save_button.setEnabled(self.context.can(CATALOG_MANAGE))
        self._apply_inheritance()
        self._update_summary()

    def set_flag(self, code: int, key: str, value: bool) -> None:
        """Tick / untick like a click (tests and keyboard helpers)."""
        self._checks[code][key].setChecked(value)

    def values(self) -> list[dict]:
        """Each group's OWN ticks (inherited ones are applied by the server)."""
        return [{"code": code, **{key: self._own[code][key] for key, _ in FLAGS}}
                for code in sorted(self._own)]

    def _update_summary(self) -> None:
        codes = list(self._own)
        counts = {key: sum(1 for c in codes if self.effective(c, key)) for key, _ in FLAGS}
        self.summary.setText(
            f"{to_persian_digits(len(codes))} گروه — "
            f"{to_persian_digits(counts['show_in_bot'])} در ربات، "
            f"{to_persian_digits(counts['is_phone'])} گروه گوشی، "
            f"{to_persian_digits(counts['price_on_inquiry'])} با استعلام"
            + ("  (ذخیره نشده)" if self._dirty else ""))
        if codes and not counts["show_in_bot"]:
            self.warning.setText("هیچ گروهی برای نمایش در ربات انتخاب نشده؛ ربات هیچ کالایی "
                                 "به مشتری نشان نمی‌دهد.")
            self.warning.setVisible(True)
        elif codes and not counts["is_phone"]:
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


def theme_color(value: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(value))
