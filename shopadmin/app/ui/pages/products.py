"""صفحهٔ محصولات — فهرست فقط‌خواندنی کالاها با جستجو، فیلتر گروه و تصویر."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...persian import format_int, format_money, format_qty, to_persian_digits
from .. import theme, widgets
from ..base_page import BasePage

HEADERS = ("کد کالا", "نام کالا", "گروه", "قیمت", "موجودی", "تصویر")

PAGE_SIZE = 50


class ProductsPage(BasePage):
    title = "محصولات"
    subtitle = "فهرست کالاها و موجودی (فقط خواندنی)"
    help_text = "کالاهای فروشگاه با قیمت و موجودی (فقط دیدن؛ تغییرات در برنامهٔ حسابداری انجام می‌شود)."

    def build_body(self) -> None:
        bar_holder = QWidget()
        bar = widgets.FlowLayout(bar_holder, spacing=10)

        group_box = QWidget()
        group_row = QHBoxLayout(group_box)
        group_row.setContentsMargins(0, 0, 0, 0)
        group_row.setSpacing(6)
        group_row.addWidget(widgets.label("گروه کالا:"))
        self.group_combo = QComboBox()
        self.group_combo.setMinimumWidth(200)
        self.group_combo.addItem("همهٔ گروه‌ها", None)
        self.group_combo.currentIndexChanged.connect(lambda _i: self.load())
        group_row.addWidget(self.group_combo)
        bar.addWidget(group_box)

        self.in_stock_only = widgets.button("فقط کالاهای موجود", variant="ghost")
        self.in_stock_only.setObjectName("Tab")
        self.in_stock_only.setCheckable(True)
        self.in_stock_only.clicked.connect(lambda: self.load())
        bar.addWidget(self.in_stock_only)

        self.search = widgets.SearchBox("جستجوی نام کالا…")
        self.search.textChanged.connect(self._on_search_changed)
        bar.addWidget(self.search)
        self.body.addWidget(bar_holder)

        panel = widgets.Panel()
        self.table = widgets.DataTable(HEADERS, selectable_rows=True, key="products")
        self.table.set_empty_state(
            "کالایی با این مشخصات پیدا نشد",
            "عبارت جستجو یا گروه انتخابی را تغییر دهید.",
            "products",
        )
        self.table.setMinimumHeight(380)
        self.table.row_activated.connect(self._open_row)
        panel.body.addWidget(self.table, 1)

        self.summary = widgets.label("", name="Muted")
        panel.body.addWidget(self.summary)

        pager = QHBoxLayout()
        pager.addStretch(1)
        self.prev_button = widgets.button("قبلی", on_click=lambda: self._change_page(-1))
        self.next_button = widgets.button("بعدی", on_click=lambda: self._change_page(1))
        self.page_label = widgets.label("", name="Muted")
        pager.addWidget(self.next_button)
        pager.addWidget(self.page_label)
        pager.addWidget(self.prev_button)
        panel.body.addLayout(pager)

        self.body.addWidget(panel, 1)

        self._items: list[dict] = []
        self._page = 1
        self._total = 0
        self._groups_loaded = False
        self._network = QNetworkAccessManager(self)
        self._image_cache: dict[str, QPixmap] = {}

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        if not self._groups_loaded:
            self._load_groups()
        self.table.set_busy(True)
        query = self.search.text().strip() or None
        group = self.group_combo.currentData()
        in_stock = self.in_stock_only.isChecked()
        page = self._page

        self.run(
            lambda: self.context.api.list_products(
                query=query, group=group, in_stock=in_stock, page=page, page_size=PAGE_SIZE
            ),
            on_success=self._on_loaded,
            on_error=self._on_error,
        )

    def _load_groups(self) -> None:
        def ok(groups: list) -> None:
            self._groups_loaded = True
            current = self.group_combo.currentData()
            self.group_combo.blockSignals(True)
            self.group_combo.clear()
            self.group_combo.addItem("همهٔ گروه‌ها", None)
            for group in groups or []:
                name = str(group.get("name") or "").strip() or f"گروه {to_persian_digits(group.get('code'))}"
                self.group_combo.addItem(name, int(group.get("code")))
            index = self.group_combo.findData(current)
            self.group_combo.setCurrentIndex(max(0, index))
            self.group_combo.blockSignals(False)

        self.run(lambda: self.context.api.list_groups(), on_success=ok,
                 on_error=lambda _m, _k: None)

    def _on_error(self, message: str, kind: str) -> None:
        self.table.fill([])
        self.show_table_error(message)
        self.default_error(message, kind)

    def _on_loaded(self, payload: dict) -> None:
        self._items = list(payload.get("items") or [])
        self._total = int(payload.get("total") or 0)
        self.table.set_busy(False)
        self._render()

    def _on_search_changed(self, _text: str) -> None:
        self._page = 1
        self._search_timer_restart()

    def _search_timer_restart(self) -> None:
        # Debounce so typing does not fire a request per keystroke.
        from PySide6.QtCore import QTimer

        if not hasattr(self, "_debounce"):
            self._debounce = QTimer(self)
            self._debounce.setSingleShot(True)
            self._debounce.setInterval(350)
            self._debounce.timeout.connect(self.load)
        self._debounce.start()

    def _change_page(self, delta: int) -> None:
        target = self._page + delta
        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        if 1 <= target <= pages:
            self._page = target
            self.load()

    # ------------------------------------------------------------------ render
    def _render(self) -> None:
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            for product in self._items:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.set_cell(row, 0, to_persian_digits(product.get("code", "")))
                self.table.set_cell(row, 1, str(product.get("name") or "—"), bold=True)

                group_code = product.get("group")
                self.table.set_cell(
                    row, 2,
                    self._group_name(group_code) if group_code is not None else "—",
                )
                self.table.set_cell(row, 3, format_money(product.get("unit_price", 0)))
                available = float(product.get("available_qty") or 0)
                self.table.set_cell(
                    row, 4, format_qty(available),
                    color=theme.DANGER if available <= 0 else (
                        theme.WARNING if available <= 5 else theme.SUCCESS_DARK
                    ),
                    bold=True,
                )
                self.table.set_widget(row, 5, self._image_cell(product))
        finally:
            self.table.setUpdatesEnabled(True)

        if not self._items:
            self.table.set_empty_state(
                "کالایی با این مشخصات پیدا نشد",
                "عبارت جستجو یا گروه انتخابی را تغییر دهید.",
                "products",
            )
        self.table._refresh_states()

        pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.summary.setText(
            f"{format_int(self._total)} کالا — نمایش صفحهٔ "
            f"{to_persian_digits(self._page)} از {to_persian_digits(pages)}"
        )
        self.page_label.setText(
            f"صفحهٔ {to_persian_digits(self._page)} از {to_persian_digits(pages)}"
        )
        self.prev_button.setEnabled(self._page > 1)
        self.next_button.setEnabled(self._page < pages)

    def _group_name(self, code: object) -> str:
        index = self.group_combo.findData(int(code)) if code is not None else -1
        if index > 0:
            return self.group_combo.itemText(index)
        return f"گروه {to_persian_digits(code)}"

    def _image_cell(self, product: dict) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(4, 2, 4, 2)
        image_url = product.get("image")
        if not image_url:
            layout.addWidget(widgets.label("—", name="Faint"))
            layout.addStretch(1)
            return holder

        label = QLabel()
        label.setFixedSize(40, 40)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"border: 1px solid {theme.BORDER}; border-radius: 6px;")
        label.setText("…")
        self._fetch_image(str(image_url), label)
        layout.addWidget(label)
        layout.addStretch(1)
        return holder

    def _fetch_image(self, url: str, target: QLabel) -> None:
        cached = self._image_cache.get(url)
        if cached is not None:
            target.setPixmap(cached.scaled(38, 38, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
            target.setText("")
            return
        absolute = url if url.startswith("http") else f"{self.context.api.base_url}{url}"
        request = QNetworkRequest(QUrl(absolute))
        reply = self._network.get(request)

        def finished() -> None:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                target.setText("—")
                reply.deleteLater()
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self._image_cache[url] = pixmap
                target.setPixmap(pixmap.scaled(38, 38, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
                target.setText("")
            else:
                target.setText("—")
            reply.deleteLater()

        reply.finished.connect(finished)

    # ------------------------------------------------------------------ detail
    def _open_row(self, row: int) -> None:
        if 0 <= row < len(self._items):
            ProductDetailDialog(self.context, self._items[row], self._group_name(
                self._items[row].get("group")
            ), self).exec()


class ProductDetailDialog(QDialog):
    def __init__(self, context, product: dict, group_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"کالای {to_persian_digits(product.get('code', ''))}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(560, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(widgets.label(
            f"کالای {to_persian_digits(product.get('code', ''))}", size=14, bold=True
        ))

        panel = widgets.Panel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        content_layout.addWidget(_row("نام کالا", str(product.get("name") or "—")))
        content_layout.addWidget(_row("گروه", group_name))
        content_layout.addWidget(_row("قیمت", format_money(product.get("unit_price", 0))))
        content_layout.addWidget(_row("موجودی قابل فروش", format_qty(product.get("available_qty", 0))))

        image_url = product.get("image")
        if image_url:
            absolute = image_url if str(image_url).startswith("http") else \
                f"{context.api.base_url}{image_url}"
            image_label = QLabel("در حال بارگذاری تصویر…")
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image_label.setMinimumHeight(240)
            image_label.setStyleSheet(
                f"border: 1px solid {theme.BORDER}; border-radius: {theme.RADIUS}px; "
                f"color: {theme.TEXT_MUTED};"
            )
            content_layout.addWidget(image_label)
            manager = QNetworkAccessManager(self)
            reply = manager.get(QNetworkRequest(QUrl(absolute)))

            def finished() -> None:
                if reply.error() == QNetworkReply.NetworkError.NoError:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(reply.readAll()):
                        image_label.setPixmap(pixmap.scaled(
                            460, 340, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        ))
                        reply.deleteLater()
                        return
                image_label.setText("تصویر این کالا در دسترس نیست")
                reply.deleteLater()

            reply.finished.connect(finished)
        else:
            content_layout.addWidget(widgets.label("این کالا تصویری ندارد.", name="Muted"))

        scroll.setWidget(content)
        panel.body.addWidget(scroll)
        root.addWidget(panel, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(widgets.button("بستن", variant="primary", on_click=self.accept))
        root.addLayout(buttons)


def _row(key: str, value: str) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    key_label = widgets.label(f"{key}:", name="Muted")
    key_label.setMinimumWidth(140)
    layout.addWidget(key_label)
    layout.addWidget(widgets.label(value, bold=True), 1)
    return holder
