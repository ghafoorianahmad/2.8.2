"""v2.12.0 زبانهٔ «ظاهر و چیدمان» در صفحهٔ «سایت» — بدون نوشتن کد.

شش بخش (زبانهٔ داخلی):
* «چیدمان کالاها»: ترتیب برندها، گوشی‌های هر برند (کشیدن یا بالاتر/پایین‌تر، «ترتیب خودکار»)
  و لوازم جانبی.
* «تازه‌ترین گوشی‌ها»: گوشی‌هایی که در صفحهٔ اصلی می‌آیند (خالی = ۴ گوشی جدیدتر، خودکار).
* «رنگ و لوگو»: یکی از رنگ‌بندی‌های آماده + لوگو.
* «بنر صفحهٔ اصلی»: متن‌ها، سه نشان، تا سه عکس.
* «بخش‌های صفحهٔ اصلی»: ترتیب و نمایش/پنهان.
* «اطلاعات فروشگاه»: آدرس، تلفن، ساعت کاری، درباره ما، پیوند ربات‌ها، کانال و نقشه.

فهرست‌ها و کارت‌ها با هر تغییر ذخیره می‌شوند؛ فرم‌های متنی با «ذخیره» (و پیش از پیش‌نمایش
و انتشار خودکار). همه‌چیز فقط روی همین رایانه است تا «انتشار در سایت».
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..persian import format_int, to_persian_digits
from ..site import catalog as cat
from ..site import look as lk
from ..site import photos as ph
from ..site.store import SiteStore
from . import theme, widgets
from .appearance import OptionCard
from .rtl import mark_ltr
from .site_dialogs import PHOTO_FILTER

NL = chr(10)


def palette_swatch(colors: tuple[str, ...], size: QSize = QSize(54, 26)) -> QPixmap:
    """Three dots of a site colour preset."""
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    d = size.height() - 4
    for n, color in enumerate(colors):
        painter.setBrush(QBrush(QColor(color)))
        painter.drawEllipse(2 + n * (d - 6), 2, d, d)
    painter.end()
    return pixmap


def read_picture(parent: QWidget) -> Optional[bytes]:
    path, _f = QFileDialog.getOpenFileName(parent, "انتخاب عکس", "", PHOTO_FILTER)
    if not path:
        return None
    try:
        data = Path(path).read_bytes()
        ph.load(data)
    except OSError:
        widgets.error(parent, "عکس", "این فایل خوانده نشد.")
        return None
    except ph.PhotoError as exc:
        widgets.error(parent, "عکس", str(exc))
        return None
    return data


class OrderBox(QWidget):
    """A list that can be arranged: drag a row, or «بالاتر» / «پایین‌تر».
    ``moved`` gives the keys in the new order. ``checkable``: a tick per row."""

    moved = Signal(list)
    toggled = Signal(str, bool)

    def __init__(self, *, checkable: bool = False, enabled: bool = True,
                 min_height: int = 160, max_height: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.checkable = checkable
        self._filling = False
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMinimumHeight(min_height)
        if max_height:
            self.list.setMaximumHeight(max_height)
        self.list.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        if enabled:
            self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.model().rowsMoved.connect(lambda *_: self._emit())
        self.list.itemChanged.connect(self._item_changed)
        box.addWidget(self.list, 1)
        side = QVBoxLayout()
        self.up_button = widgets.button("بالاتر ↑", on_click=lambda: self.step(-1))
        self.down_button = widgets.button("پایین‌تر ↓", on_click=lambda: self.step(1))
        for b in (self.up_button, self.down_button):
            b.setEnabled(enabled)
            side.addWidget(b)
        side.addStretch(1)
        box.addLayout(side)
        self.editable = enabled

    def fill(self, rows: list[tuple[str, str]], *, checked: dict[str, bool] | None = None,
             icons: dict[str, QIcon] | None = None) -> None:
        """``rows``: (key, text)."""
        current = self.current_key()
        self._filling = True
        self.list.clear()
        for key, text in rows:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, key)
            flags = item.flags() | Qt.ItemFlag.ItemIsDragEnabled
            flags &= ~Qt.ItemFlag.ItemIsDropEnabled
            if self.checkable:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
                item.setCheckState(Qt.CheckState.Checked if (checked or {}).get(key, True)
                                   else Qt.CheckState.Unchecked)
            if not self.editable:
                flags &= ~(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            item.setFlags(flags)
            if icons and key in icons:
                item.setIcon(icons[key])
            self.list.addItem(item)
            if key == current:
                self.list.setCurrentItem(item)
        self._filling = False

    def keys(self) -> list[str]:
        return [self.list.item(n).data(Qt.ItemDataRole.UserRole) for n in range(self.list.count())]

    def current_key(self) -> str:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else ""

    def step(self, delta: int) -> None:
        row = self.list.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.list.count():
            return
        self._filling = True
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)
        self._filling = False
        self._emit()

    def _emit(self) -> None:
        if not self._filling:
            self.moved.emit(self.keys())

    def _item_changed(self, item: QListWidgetItem) -> None:
        if not self._filling and self.checkable:
            self.toggled.emit(item.data(Qt.ItemDataRole.UserRole),
                              item.checkState() == Qt.CheckState.Checked)


class PickPhonesDialog(widgets.ResponsiveDialog):
    """«افزودن به تازه‌ترین گوشی‌ها»: tick the phones (search by name)."""

    def __init__(self, phones: list[dict], room: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("افزودن به «تازه‌ترین گوشی‌ها»")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(460)
        self.room = room
        self.chosen: list[str] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.addWidget(widgets.label("افزودن به «تازه‌ترین گوشی‌ها»", size=15, bold=True))
        root.addWidget(widgets.label(f"حداکثر {format_int(room)} گوشی دیگر را تیک بزنید.",
                                     name="Muted", wrap=True))
        self.search = widgets.SearchBox("جستجوی گوشی…")
        self.search.textChanged.connect(self._filter)
        root.addWidget(self.search)
        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        for phone in phones:
            item = QListWidgetItem(phone["name"])
            item.setData(Qt.ItemDataRole.UserRole, phone["code"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)
        root.addWidget(self.list, 1)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        root.addWidget(self.error_label)
        root.addLayout(widgets.footer(
            widgets.button("افزودن", icon_name="plus", variant="primary", on_click=self._accept),
            close=widgets.button("انصراف", on_click=self.reject)))

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        for n in range(self.list.count()):
            item = self.list.item(n)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _accept(self) -> None:
        picked = [self.list.item(n).data(Qt.ItemDataRole.UserRole) for n in range(self.list.count())
                  if self.list.item(n).checkState() == Qt.CheckState.Checked]
        if not picked:
            self.error_label.setText("دست‌کم یک گوشی را تیک بزنید.")
            return
        if len(picked) > self.room:
            self.error_label.setText(f"فقط {format_int(self.room)} گوشی دیگر جا دارد.")
            return
        self.chosen = picked
        self.accept()


class LookTab(QWidget):
    """The «ظاهر و چیدمان» tab. ``changed`` after every saved change (the page
    refreshes its preview)."""

    changed = Signal()

    def __init__(self, store: SiteStore, *, can_manage: bool,
                 notify: Callable[[str], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.can_manage = can_manage
        self.notify = notify
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._scroll(self._arrange_tab()), "چیدمان کالاها")
        self.tabs.addTab(self._scroll(self._featured_tab()), "تازه‌ترین گوشی‌ها")
        self.tabs.addTab(self._scroll(self._colors_tab()), "رنگ و لوگو")
        self.tabs.addTab(self._scroll(self._banner_tab()), "بنر صفحهٔ اصلی")
        self.tabs.addTab(self._scroll(self._sections_tab()), "بخش‌های صفحهٔ اصلی")
        self.tabs.addTab(self._scroll(self._store_tab()), "اطلاعات فروشگاه")
        box.addWidget(self.tabs, 1)
        self.actions = QWidget()
        self.actions_flow = widgets.FlowLayout(self.actions, spacing=8)
        box.addWidget(self.actions)
        box.addWidget(widgets.label(
            "تغییرها روی همین رایانه ذخیره می‌شود؛ با «پیش‌نمایش در مرورگر» همان سایت را با این "
            "تغییرها ببینید و با «انتشار در سایت» بفرستید (تا ۴۸ ساعت برگرداندنی است).",
            name="Muted", wrap=True))
        self.fill()

    @staticmethod
    def _scroll(content: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(content)
        return area

    def add_action(self, button) -> None:
        self.actions_flow.addWidget(button)

    def _saved(self, message: str = "ذخیره شد؛ با «انتشار در سایت» در سایت دیده می‌شود.") -> None:
        self.notify(message)
        # later: a list may still be inside its own drag-and-drop signal
        QTimer.singleShot(0, self.changed.emit)

    # ---- 1. arrangement ------------------------------------------------------------------
    def _arrange_tab(self) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)
        brands = widgets.Panel("ترتیب برندها در صفحهٔ اصلی")
        self.brand_order = OrderBox(enabled=self.can_manage, min_height=96, max_height=120)
        self.brand_order.moved.connect(self._brands_moved)
        brands.body.addWidget(self.brand_order)
        box.addWidget(brands)

        phones = widgets.Panel("ترتیب گوشی‌ها در صفحهٔ هر برند")
        row = QHBoxLayout()
        row.addWidget(widgets.label("برند:"))
        self.phone_brand = QComboBox()
        self.phone_brand.currentIndexChanged.connect(lambda _i: self._fill_phones())
        row.addWidget(self.phone_brand, 1)
        phones.body.addLayout(row)
        self.phone_order = OrderBox(enabled=self.can_manage, min_height=200)
        self.phone_order.moved.connect(self._phones_moved)
        phones.body.addWidget(self.phone_order)
        self.phone_mode = widgets.label("", name="Muted", wrap=True)
        phones.body.addWidget(self.phone_mode)
        self.auto_button = widgets.button("ترتیب خودکار (جدیدترین اول)", icon_name="refresh",
                                          on_click=self._auto_order)
        self.auto_button.setEnabled(self.can_manage)
        phones.body.addWidget(self.auto_button, 0, Qt.AlignmentFlag.AlignRight)
        box.addWidget(phones)

        accessories = widgets.Panel("ترتیب لوازم جانبی در صفحهٔ اصلی")
        self.accessory_order = OrderBox(enabled=self.can_manage, min_height=150)
        self.accessory_order.moved.connect(lambda keys: (self.store.reorder(keys), self._saved()))
        accessories.body.addWidget(self.accessory_order)
        box.addWidget(accessories)
        box.addStretch(1)
        return tab

    def _brands_moved(self, keys: list[str]) -> None:
        self.store.set_brand_order(keys)
        self._fill_brand_combo()
        self._saved()

    def _phones_moved(self, keys: list[str]) -> None:
        self.store.reorder(keys)
        self.store.update_look(lambda look: look.update(phone_order=lk.PHONE_ORDER_MANUAL))
        self._fill_phone_mode()
        self._saved()

    def _auto_order(self) -> None:
        self.store.sort_phones_newest()
        self._fill_phones()
        self._saved("گوشی‌ها دوباره خودکار (جدیدترین اول) چیده شدند.")

    def _fill_brand_combo(self) -> None:
        current = self.phone_brand.currentData()
        self.phone_brand.blockSignals(True)
        self.phone_brand.clear()
        for brand in self.store.brands():
            self.phone_brand.addItem(brand["name"], brand["key"])
        index = self.phone_brand.findData(current)
        self.phone_brand.setCurrentIndex(max(0, index))
        self.phone_brand.blockSignals(False)

    def _fill_phones(self) -> None:
        brand = self.phone_brand.currentData()
        self.phone_order.fill([(p["code"], p["name"] + (" (پنهان)" if p["hidden"] else ""))
                               for p in self.store.items(cat.KIND_PHONE) if p["brand"] == brand])
        self._fill_phone_mode()

    def _fill_phone_mode(self) -> None:
        manual = self.store.look()["phone_order"] == lk.PHONE_ORDER_MANUAL
        self.phone_mode.setText(
            "ترتیب دستی: سایت گوشی‌ها را دقیقاً به همین ترتیب نشان می‌دهد." if manual else
            "ترتیب خودکار: سایت جدیدترین گوشی را اول نشان می‌دهد. با جابه‌جا کردن یک گوشی، ترتیب "
            "دستی می‌شود.")

    # ---- 2. featured ---------------------------------------------------------------------
    def _featured_tab(self) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)
        panel = widgets.Panel("«تازه‌ترین گوشی‌های فروشگاه» در صفحهٔ اصلی")
        panel.body.addWidget(widgets.label(
            f"تا {format_int(lk.FEATURED_MAX)} گوشی را انتخاب و مرتب کنید. اگر فهرست خالی باشد، "
            "سایت خودش ۴ گوشی جدیدتر را نشان می‌دهد.", name="Muted", wrap=True))
        self.featured = OrderBox(enabled=self.can_manage, min_height=200)
        self.featured.moved.connect(self._featured_moved)
        panel.body.addWidget(self.featured)
        holder = QWidget()
        flow = widgets.FlowLayout(holder, spacing=8)
        self.featured_add = widgets.button("افزودن گوشی…", icon_name="plus", variant="primary",
                                           on_click=self._featured_add)
        self.featured_remove = widgets.button("برداشتن از فهرست", icon_name="trash",
                                              on_click=self._featured_remove)
        self.featured_clear = widgets.button("خودکار (۴ گوشی جدیدتر)", icon_name="refresh",
                                             on_click=self._featured_clear)
        for b in (self.featured_add, self.featured_remove, self.featured_clear):
            b.setEnabled(self.can_manage)
            flow.addWidget(b)
        panel.body.addWidget(holder)
        self.featured_state = widgets.label("", name="Muted", wrap=True)
        panel.body.addWidget(self.featured_state)
        box.addWidget(panel)
        box.addStretch(1)
        return tab

    def _visible_phones(self) -> list[dict]:
        return [p for p in self.store.items(cat.KIND_PHONE) if not p["hidden"]]

    def _featured_moved(self, keys: list[str]) -> None:
        self.store.update_look(lambda look: look.update(featured=keys))
        self._saved()

    def _featured_add(self) -> None:
        chosen = self.store.look()["featured"]
        room = lk.FEATURED_MAX - len(chosen)
        if room <= 0:
            self.notify(f"فهرست پر است (حداکثر {format_int(lk.FEATURED_MAX)} گوشی).")
            return
        dialog = PickPhonesDialog([p for p in self._visible_phones() if p["code"] not in chosen],
                                  room, self)
        if dialog.exec():
            self.store.update_look(lambda look: look.update(featured=chosen + dialog.chosen))
            self._fill_featured()
            self._saved()

    def _featured_remove(self) -> None:
        key = self.featured.current_key()
        if not key:
            self.notify("یک گوشی را از فهرست انتخاب کنید.")
            return
        self.store.update_look(lambda look: look.update(
            featured=[c for c in look["featured"] if c != key]))
        self._fill_featured()
        self._saved()

    def _featured_clear(self) -> None:
        self.store.update_look(lambda look: look.update(featured=[]))
        self._fill_featured()
        self._saved("«تازه‌ترین گوشی‌ها» دوباره خودکار شد.")

    def _fill_featured(self) -> None:
        names = {p["code"]: p for p in self.store.items(cat.KIND_PHONE)}
        chosen = self.store.look()["featured"]
        self.featured.fill([(c, names[c]["name"] + (" (پنهان؛ در سایت نمی‌آید)"
                                                    if names[c]["hidden"] else ""))
                            for c in chosen if c in names])
        self.featured_state.setText(
            "خودکار: سایت ۴ گوشی جدیدتر را نشان می‌دهد." if not chosen else
            f"{format_int(len(chosen))} گوشی انتخاب شده است.")

    # ---- 3. colours and logo ----------------------------------------------------------------
    def _colors_tab(self) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)
        panel = widgets.Panel("رنگ‌بندی سایت")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.palette_group = QButtonGroup(self)
        self.palette_group.setExclusive(True)
        self.palette_cards: dict[str, OptionCard] = {}
        for n, (key, name, colors) in enumerate(lk.PALETTES):
            card = OptionCard(name, palette_swatch(colors))
            card.setProperty("value", key)
            card.setEnabled(self.can_manage)
            self.palette_group.addButton(card)
            grid.addWidget(card, n // 3, n % 3)
            grid.setColumnStretch(n % 3, 1)
            self.palette_cards[key] = card
        self.palette_group.buttonClicked.connect(self._palette_clicked)
        panel.body.addLayout(grid)
        panel.body.addWidget(widgets.label(
            "روز و شب سایت همان می‌ماند؛ فقط رنگ دکمه‌ها، درخشش‌ها و نشان‌ها عوض می‌شود.",
            name="Muted", wrap=True))
        box.addWidget(panel)

        logo = widgets.Panel("لوگو")
        row = QHBoxLayout()
        self.logo_view = QLabel()
        self.logo_view.setFixedSize(72, 72)
        self.logo_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_view.setObjectName("Panel")
        row.addWidget(self.logo_view)
        self.logo_state = widgets.label("", wrap=True)
        row.addWidget(self.logo_state, 1)
        logo.body.addLayout(row)
        holder = QWidget()
        flow = widgets.FlowLayout(holder, spacing=8)
        self.logo_pick = widgets.button("انتخاب لوگو…", icon_name="image", on_click=self._pick_logo)
        self.logo_clear = widgets.button("برداشتن لوگو", icon_name="trash",
                                         on_click=self._clear_logo)
        for b in (self.logo_pick, self.logo_clear):
            b.setEnabled(self.can_manage)
            flow.addWidget(b)
        logo.body.addWidget(holder)
        logo.body.addWidget(widgets.label(
            "لوگو کنار نام فروشگاه، بالای همهٔ صفحه‌ها و پایین صفحه می‌آید (مربعی، زمینهٔ شفاف "
            "بهتر است). بدون لوگو همان نشان «۲» می‌ماند.", name="Muted", wrap=True))
        box.addWidget(logo)
        box.addStretch(1)
        return tab

    def _palette_clicked(self, card) -> None:
        key = str(card.property("value"))
        self.store.update_look(lambda look: look.update(palette=key))
        self._saved(f"رنگ‌بندی «{lk.PALETTE_NAMES[key]}» انتخاب شد.")

    def _pick_logo(self) -> None:
        data = read_picture(self)
        if data is None:
            return
        try:
            name, _notes = self.store.add_look_photo("logo", data)
        except ph.PhotoError as exc:
            widgets.error(self, "لوگو", str(exc))
            return
        self.store.update_look(lambda look: look.update(logo=name))
        self._fill_logo()
        self._saved("لوگو ذخیره شد.")

    def _clear_logo(self) -> None:
        self.store.update_look(lambda look: look.update(logo=""))
        self._fill_logo()
        self._saved("لوگو برداشته شد؛ نشان «۲» نشان داده می‌شود.")

    def _fill_logo(self) -> None:
        name = self.store.look()["logo"]
        path = self.store.look_photo_path(name) if name else None
        if path is not None and path.is_file():
            self.logo_view.setPixmap(QPixmap(str(path)).scaled(
                64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            self.logo_state.setText("لوگوی فروشگاه انتخاب شده است.")
        else:
            self.logo_view.clear()
            self.logo_view.setText(to_persian_digits("2"))
            self.logo_state.setText("لوگویی انتخاب نشده؛ نشان «۲» نشان داده می‌شود.")
        self.logo_clear.setEnabled(self.can_manage and bool(name))

    # ---- 4. banner ---------------------------------------------------------------------------
    def _banner_tab(self) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)
        texts = widgets.Panel("متن‌های بنر")
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        self.hero_inputs: dict[str, QLineEdit] = {}
        for n, (key, title, hint) in enumerate((
                ("eyebrow", "برچسب بالا:", "مثلاً عصر ارتباطات ۲ · مشهد"),
                ("title", "عنوان:", "خط اول عنوان"),
                ("highlight", "بخش رنگی عنوان:", "خط دوم، رنگی"))):
            edit = QLineEdit()
            edit.setMaxLength(lk.LIMITS[key])
            edit.setPlaceholderText(hint)
            edit.textEdited.connect(lambda _t: self._dirty("banner"))
            form.addWidget(widgets.label(title), n, 0)
            form.addWidget(edit, n, 1)
            self.hero_inputs[key] = edit
        texts.body.addLayout(form)
        texts.body.addWidget(widgets.label("توضیح زیر عنوان:"))
        self.hero_lede = QPlainTextEdit()
        self.hero_lede.setFixedHeight(80)
        self.hero_lede.textChanged.connect(lambda: self._dirty("banner"))
        texts.body.addWidget(self.hero_lede)
        texts.body.addWidget(widgets.label("سه نشان زیر بنر:", bold=True))
        badges = QGridLayout()
        badges.setHorizontalSpacing(10)
        self.badge_inputs: list[tuple[QLineEdit, QLineEdit]] = []
        for n in range(lk.BADGES):
            title, text = QLineEdit(), QLineEdit()
            title.setMaxLength(lk.LIMITS["badge_title"])
            text.setMaxLength(lk.LIMITS["badge_text"])
            title.setPlaceholderText("عنوان کوتاه")
            text.setPlaceholderText("یک جملهٔ کوتاه")
            for edit in (title, text):
                edit.textEdited.connect(lambda _t: self._dirty("banner"))
            badges.addWidget(widgets.label(f"نشان {format_int(n + 1)}:"), n, 0)
            badges.addWidget(title, n, 1)
            badges.addWidget(text, n, 2)
            badges.setColumnStretch(2, 2)
            badges.setColumnStretch(1, 1)
            self.badge_inputs.append((title, text))
        texts.body.addLayout(badges)
        self.banner_dirty = widgets.label("", color=theme.WARNING_TEXT, wrap=True)
        texts.body.addWidget(self.banner_dirty)
        holder = QWidget()
        flow = widgets.FlowLayout(holder, spacing=8)
        self.banner_save = widgets.button("ذخیرهٔ متن‌های بنر", icon_name="save", variant="primary",
                                          on_click=self.save_banner)
        self.banner_reset = widgets.button("متن‌های پیش‌فرض", icon_name="refresh",
                                           on_click=self._reset_banner)
        for b in (self.banner_save, self.banner_reset):
            b.setEnabled(self.can_manage)
            flow.addWidget(b)
        texts.body.addWidget(holder)
        box.addWidget(texts)

        pictures = widgets.Panel("عکس‌های بنر")
        pictures.body.addWidget(widgets.label(
            f"تا {format_int(lk.BANNER_MAX)} عکس افقی (۲ به ۱؛ خودکار ۱۲۰۰×۶۰۰ می‌شود). عکس اول "
            "وسط و بزرگ‌تر است. بدون عکس، همان عکس‌های سه برند می‌ماند.", name="Muted", wrap=True))
        self.banner_list = OrderBox(enabled=self.can_manage, min_height=140)
        self.banner_list.list.setIconSize(QSize(120, 60))
        self.banner_list.moved.connect(lambda keys: (self.store.update_look(
            lambda look: look["hero"].update(images=keys)), self._saved()))
        pictures.body.addWidget(self.banner_list)
        holder = QWidget()
        flow = widgets.FlowLayout(holder, spacing=8)
        self.banner_add = widgets.button("افزودن عکس…", icon_name="image", on_click=self._add_banner)
        self.banner_remove = widgets.button("برداشتن عکس", icon_name="trash",
                                            on_click=self._remove_banner)
        for b in (self.banner_add, self.banner_remove):
            b.setEnabled(self.can_manage)
            flow.addWidget(b)
        pictures.body.addWidget(holder)
        box.addWidget(pictures)
        box.addStretch(1)
        return tab

    def _banner_values(self, look: dict) -> None:
        hero = look["hero"]
        for key, edit in self.hero_inputs.items():
            hero[key] = edit.text()
        hero["lede"] = self.hero_lede.toPlainText()
        hero["badges"] = [{"title": t.text(), "text": x.text()} for t, x in self.badge_inputs]

    def save_banner(self) -> bool:
        if not any(e.text().strip() for e in (self.hero_inputs["title"],
                                              self.hero_inputs["highlight"])):
            widgets.error(self, "بنر", "عنوان بنر را بنویسید.")
            return False
        self.store.update_look(self._banner_values)
        self._clean("banner")
        self._saved("متن‌های بنر ذخیره شد.")
        return True

    def _reset_banner(self) -> None:
        default = lk.default_look()["hero"]
        self.store.update_look(lambda look: look["hero"].update(
            {k: v for k, v in default.items() if k != "images"}))
        self._fill_banner()
        self._saved("متن‌های بنر به پیش‌فرض برگشت.")

    def _add_banner(self) -> None:
        images = self.store.look()["hero"]["images"]
        if len(images) >= lk.BANNER_MAX:
            self.notify(f"بنر حداکثر {format_int(lk.BANNER_MAX)} عکس دارد؛ اول یکی را بردارید.")
            return
        data = read_picture(self)
        if data is None:
            return
        try:
            name, notes = self.store.add_look_photo("banner", data)
        except ph.PhotoError as exc:
            widgets.error(self, "عکس بنر", str(exc))
            return
        self.store.update_look(lambda look: look["hero"].update(images=images + [name]))
        self._fill_banner_pictures()
        self._saved(" ".join(["عکس بنر اضافه شد."] + notes))

    def _remove_banner(self) -> None:
        key = self.banner_list.current_key()
        if not key:
            self.notify("یک عکس را انتخاب کنید.")
            return
        self.store.update_look(lambda look: look["hero"].update(
            images=[n for n in look["hero"]["images"] if n != key]))
        self._fill_banner_pictures()
        self._saved("عکس از بنر برداشته شد.")

    def _fill_banner(self) -> None:
        hero = self.store.look()["hero"]
        for key, edit in self.hero_inputs.items():
            edit.setText(hero[key])
        self.hero_lede.blockSignals(True)
        self.hero_lede.setPlainText(hero["lede"])
        self.hero_lede.blockSignals(False)
        for (title, text), badge in zip(self.badge_inputs, hero["badges"]):
            title.setText(badge["title"])
            text.setText(badge["text"])
        self._clean("banner")
        self._fill_banner_pictures()

    def _fill_banner_pictures(self) -> None:
        names = self.store.look()["hero"]["images"]
        icons = {n: QIcon(QPixmap(str(self.store.look_photo_path(n)))) for n in names
                 if self.store.look_photo_path(n).is_file()}
        self.banner_list.fill([(n, ("عکس وسط (بزرگ)" if i == 0 else f"عکس {format_int(i + 1)}"))
                               for i, n in enumerate(names)], icons=icons)

    # ---- 5. sections ---------------------------------------------------------------------------
    def _sections_tab(self) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)
        panel = widgets.Panel("بخش‌های صفحهٔ اصلی")
        panel.body.addWidget(widgets.label(
            "بنر همیشه اول است. ترتیب بقیه را با کشیدن یا «بالاتر/پایین‌تر» عوض کنید؛ تیک = "
            "نمایش در سایت.", name="Muted", wrap=True))
        self.sections = OrderBox(checkable=True, enabled=self.can_manage, min_height=210)
        self.sections.moved.connect(self._sections_changed)
        self.sections.toggled.connect(lambda *_: self._sections_changed(self.sections.keys()))
        panel.body.addWidget(self.sections)
        box.addWidget(panel)
        box.addStretch(1)
        return tab

    def _sections_changed(self, keys: list[str]) -> None:
        shown = {}
        for n in range(self.sections.list.count()):
            item = self.sections.list.item(n)
            shown[item.data(Qt.ItemDataRole.UserRole)] = (
                item.checkState() == Qt.CheckState.Checked)
        if not any(shown.values()):
            self.notify("دست‌کم یک بخش باید در سایت بماند.")
            self._fill_sections()
            return
        self.store.update_look(lambda look: look.update(
            sections=[{"key": k, "show": shown.get(k, True)} for k in keys]))
        self._saved()

    def _fill_sections(self) -> None:
        rows = self.store.look()["sections"]
        self.sections.fill([(s["key"], lk.SECTION_NAMES[s["key"]]) for s in rows],
                           checked={s["key"]: s["show"] for s in rows})

    # ---- 6. store info ---------------------------------------------------------------------------
    def _store_tab(self) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)
        panel = widgets.Panel("اطلاعات فروشگاه")
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        self.store_inputs: dict[str, QLineEdit] = {}
        rows = (("address", "آدرس کامل:", "", False), ("address_short", "آدرس کوتاه:",
                                                         "مثلاً ۱۷ شهریور شمالی ۶، مشهد", False),
                ("phone", "تلفن:", "09155000432", True), ("bale", "ربات بله:",
                                                           "@asrertebatat2_bot", True),
                ("telegram", "ربات تلگرام:", "@asrertebatat2_bot", True),
                ("telegram_channel", "کانال تلگرام:", "خالی = «به‌زودی»", True),
                ("map", "پیوند نقشه:", "https://nshn.ir/…", True))
        for n, (key, title, hint, ltr) in enumerate(rows):
            edit = QLineEdit()
            edit.setPlaceholderText(hint)
            edit.setMaxLength(lk.LIMITS.get(key, 300))
            if ltr:
                mark_ltr(edit)
            edit.textEdited.connect(lambda _t: self._dirty("store"))
            form.addWidget(widgets.label(title), n, 0)
            form.addWidget(edit, n, 1)
            self.store_inputs[key] = edit
        panel.body.addLayout(form)
        panel.body.addWidget(widgets.label("ساعت کاری (در صفحهٔ «تماس»):", bold=True))
        hours = QGridLayout()
        hours.setHorizontalSpacing(10)
        self.hour_inputs: list[tuple[QLineEdit, QLineEdit]] = []
        for n in range(lk.HOURS_MAX):
            day, time = QLineEdit(), QLineEdit()
            day.setPlaceholderText("مثلاً شنبه تا پنج‌شنبه · صبح")
            time.setPlaceholderText("مثلاً ۹:۳۰ تا ۱۴")
            day.setMaxLength(lk.LIMITS["hours_label"])
            time.setMaxLength(lk.LIMITS["hours_value"])
            for edit in (day, time):
                edit.textEdited.connect(lambda _t: self._dirty("store"))
            hours.addWidget(day, n, 0)
            hours.addWidget(time, n, 1)
            self.hour_inputs.append((day, time))
        panel.body.addLayout(hours)
        panel.body.addWidget(widgets.label("درباره ما (پایین همهٔ صفحه‌ها):"))
        self.about = QPlainTextEdit()
        self.about.setFixedHeight(90)
        self.about.textChanged.connect(lambda: self._dirty("store"))
        panel.body.addWidget(self.about)
        panel.body.addWidget(widgets.label(
            "خالی گذاشتن ربات بله/تلگرام یعنی همان پیوند فعلی سایت؛ کانال و نقشهٔ خالی در سایت "
            "«به‌زودی» نشان داده می‌شود.", name="Muted", wrap=True))
        self.store_error = widgets.label("", color=theme.DANGER, wrap=True)
        panel.body.addWidget(self.store_error)
        self.store_dirty = widgets.label("", color=theme.WARNING_TEXT, wrap=True)
        panel.body.addWidget(self.store_dirty)
        holder = QWidget()
        flow = widgets.FlowLayout(holder, spacing=8)
        self.store_save = widgets.button("ذخیرهٔ اطلاعات فروشگاه", icon_name="save",
                                         variant="primary", on_click=self.save_store)
        self.store_reset = widgets.button("اطلاعات پیش‌فرض", icon_name="refresh",
                                          on_click=self._reset_store)
        for b in (self.store_save, self.store_reset):
            b.setEnabled(self.can_manage)
            flow.addWidget(b)
        panel.body.addWidget(holder)
        box.addWidget(panel)
        box.addStretch(1)
        return tab

    def store_problems(self) -> list[str]:
        problems = []
        phone = self.store_inputs["phone"].text().strip()
        if phone and not lk.normalize_phone(phone):
            problems.append("تلفن درست نیست (مثلاً 09155000432 یا 05131234567).")
        for key in lk.STORE_LINKS:
            problem = lk.normalize_link(key, self.store_inputs[key].text())[1]
            if problem:
                problems.append(problem)
        return problems

    def save_store(self) -> bool:
        problems = self.store_problems()
        self.store_error.setText(NL.join(problems))
        if problems:
            return False

        def change(look: dict) -> None:
            store = look["store"]
            for key in ("address", "address_short", "phone") + lk.STORE_LINKS:
                store[key] = self.store_inputs[key].text()
            store["hours"] = [[d.text(), t.text()] for d, t in self.hour_inputs]
            store["about"] = self.about.toPlainText()

        self.store.update_look(change)
        self._fill_store()
        self._saved("اطلاعات فروشگاه ذخیره شد.")
        return True

    def _reset_store(self) -> None:
        self.store.update_look(lambda look: look.update(store=lk.default_look()["store"]))
        self._fill_store()
        self._saved("اطلاعات فروشگاه به پیش‌فرض (اطلاعات فعلی سایت) برگشت.")

    def _fill_store(self) -> None:
        store = self.store.look()["store"]
        for key, edit in self.store_inputs.items():
            edit.setText(store[key])
        for n, (day, time) in enumerate(self.hour_inputs):
            row = store["hours"][n] if n < len(store["hours"]) else ["", ""]
            day.setText(row[0])
            time.setText(row[1])
        self.about.blockSignals(True)
        self.about.setPlainText(store["about"])
        self.about.blockSignals(False)
        self.store_error.setText("")
        self._clean("store")

    # ---- dirty forms -------------------------------------------------------------------------------
    def _dirty(self, form: str) -> None:
        label = self.banner_dirty if form == "banner" else self.store_dirty
        label.setText("تغییر ذخیره‌نشده دارد؛ «ذخیره» را بزنید.")

    def _clean(self, form: str) -> None:
        (self.banner_dirty if form == "banner" else self.store_dirty).setText("")

    def is_dirty(self) -> bool:
        return bool(self.banner_dirty.text() or self.store_dirty.text())

    def save_pending(self) -> bool:
        """Before a preview / publish: save the edited forms. False = a form has a
        problem (it is shown; nothing is published)."""
        if self.banner_dirty.text() and not self.save_banner():
            self.tabs.setCurrentIndex(3)
            return False
        if self.store_dirty.text() and not self.save_store():
            self.tabs.setCurrentIndex(5)
            return False
        return True

    # ---- everything -------------------------------------------------------------------------------
    def fill(self) -> None:
        """Every part, the text forms too (on load, after «خواندن از سایت» / a restore)."""
        self.fill_lists()
        self._fill_banner()
        self._fill_store()

    def fill_lists(self) -> None:
        """The lists, cards and pictures (never the text forms being edited)."""
        brands = self.store.brands()
        self.brand_order.fill([(b["key"], b["name"]) for b in brands])
        self._fill_brand_combo()
        self._fill_phones()
        self.accessory_order.fill([(a["code"], a["name"] + (" (پنهان)" if a["hidden"] else ""))
                                   for a in self.store.items(cat.KIND_ACCESSORY)])
        self._fill_featured()
        palette = self.store.look()["palette"]
        for key, card in self.palette_cards.items():
            card.setChecked(key == palette)
        self._fill_logo()
        self._fill_banner_pictures()
        self._fill_sections()
