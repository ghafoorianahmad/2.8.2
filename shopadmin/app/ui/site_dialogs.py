"""v2.11.0 پنجره‌های بخش «سایت»: افزودن / ویرایش گوشی، لوازم جانبی، خواندن PDF لوازم جانبی.

همه‌چیز روی همین رایانه ذخیره می‌شود (``app.site.store.SiteStore``)؛ عکس‌ها خودکار به
اندازهٔ استاندارد سایت (۱۲۸۰×۱۰۲۴، زمینهٔ روشن) می‌روند.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..persian import format_int, to_persian_digits
from ..site import catalog as cat
from ..site import photos as ph
from ..site.store import SiteDataError, SiteStore
from . import theme, widgets
from .rtl import mark_ltr

NL = chr(10)
PHOTO_FILTER = "عکس (*.jpg *.jpeg *.png *.webp)"


def specs_to_text(specs: list) -> str:
    return NL.join(f"{k}: {v}" for k, v in specs or [])


def parse_specs_text(text: str) -> list[list[str]]:
    """«عنوان: مقدار» per line (``:`` or ``：``); other lines are ignored."""
    out = []
    for line in (text or "").splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            key, sep, value = line.partition("：")
        if sep and key.strip() and value.strip():
            out.append([key.strip()[:40], value.strip()[:160]])
    return out[:cat.MAX_SPECS]


def read_photo(parent: QWidget) -> Optional[bytes]:
    path, _filter = QFileDialog.getOpenFileName(parent, "انتخاب عکس", "", PHOTO_FILTER)
    if not path:
        return None
    try:
        data = Path(path).read_bytes()
        ph.load(data)                      # a clear message now, not at «ذخیره»
    except OSError:
        widgets.error(parent, "عکس", "این فایل خوانده نشد.")
        return None
    except ph.PhotoError as exc:
        widgets.error(parent, "عکس", str(exc))
        return None
    return data


class _FormDialog(widgets.ResponsiveDialog):
    def __init__(self, store: SiteStore, title: str, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.store = store
        self.saved: Optional[dict] = None
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(600)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 20, 24, 20)
        self.root.setSpacing(10)
        self.root.addWidget(widgets.label(title, size=15, bold=True))
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)

    def row(self, text: str, widget: QWidget, stretch: int = 1) -> QHBoxLayout:
        line = QHBoxLayout()
        line.addWidget(widgets.label(text))
        line.addWidget(widget, stretch)
        self.root.addLayout(line)
        return line

    def finish(self, save_text: str = "ذخیره") -> None:
        self.root.addWidget(self.error_label)
        self.root.addLayout(widgets.footer(
            widgets.button(save_text, icon_name="check", variant="primary", on_click=self._save),
            close=widgets.button("انصراف", on_click=self.reject)))

    def _save(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


# ---- phone ---------------------------------------------------------------------------
class PhoneDialog(_FormDialog):
    """«افزودن گوشی جدید» / ویرایش: برند، نام، رنگ‌ها (هر رنگ با عکس خودش)، مشخصات."""

    def __init__(self, store: SiteStore, item: Optional[dict] = None,
                 parent: QWidget | None = None) -> None:
        self.item = dict(item or {})
        self.new = item is None
        super().__init__(store, "افزودن گوشی جدید" if self.new else "ویرایش گوشی", parent)
        data = store.load()
        self.brand = QComboBox()
        for brand in data["brands"]:
            self.brand.addItem(brand["name"], brand["key"])
        self.brand.setCurrentIndex(max(0, self.brand.findData(self.item.get("brand"))))
        self.row("برند:", self.brand)
        self.name = QLineEdit(self.item.get("name", ""))
        self.name.setPlaceholderText("مثلاً Galaxy A57")
        self.name.setMaxLength(120)
        self.row("نام گوشی:", self.name)
        self.code = QLineEdit(self.item.get("code", ""))
        self.code.setPlaceholderText("خودکار از نام")
        self.code.setMaxLength(cat.CODE_MAX)
        mark_ltr(self.code)
        self.code.setReadOnly(not self.new)       # a published code never changes
        self.row("کد مدل:", self.code)
        if self.new:
            self.name.textChanged.connect(self._auto_code)
        line = QHBoxLayout()
        line.addWidget(widgets.label("رده:"))
        self.tier = QComboBox()
        self.tier.setEditable(True)
        self.tier.addItems(cat.TIERS)
        self.tier.setCurrentText(self.item.get("tier") or cat.TIERS[1])
        line.addWidget(self.tier, 1)
        line.addWidget(widgets.label("سال عرضه:"))
        self.year = QSpinBox()
        self.year.setRange(2015, 2100)
        self.year.setValue(int(self.item.get("release_year") or 2026))
        line.addWidget(self.year)
        self.root.addLayout(line)

        self.root.addWidget(widgets.label("رنگ‌ها (هر رنگ عکس خودش را دارد):", bold=True))
        self.colors = QTableWidget(0, 2)
        self.colors.setHorizontalHeaderLabels(["نام رنگ", "عکس"])
        self.colors.horizontalHeader().setStretchLastSection(True)
        self.colors.verticalHeader().setVisible(False)
        self.colors.setMinimumHeight(150)
        self.root.addWidget(self.colors)
        #: colour row -> new photo bytes (saved on «ذخیره»)
        self._photos: dict[int, bytes] = {}
        self._card: Optional[bytes] = None
        for color in self.item.get("colors") or []:
            self._add_color_row(color.get("name", ""), color.get("image", ""))
        buttons = QWidget()
        flow = widgets.FlowLayout(buttons, spacing=8)
        for b in (widgets.button("افزودن رنگ", icon_name="plus", on_click=self._new_color),
                  widgets.button("عکس این رنگ…", icon_name="image", on_click=self._color_photo),
                  widgets.button("حذف رنگ", icon_name="trash", on_click=self._remove_color),
                  widgets.button("عکس کارت…", icon_name="image", on_click=self._card_photo)):
            flow.addWidget(b)
        self.root.addWidget(buttons)
        self.card_label = widgets.label("", name="Muted", wrap=True)
        self.root.addWidget(self.card_label)
        self._show_card()

        self.root.addWidget(widgets.label("مشخصات — هر مورد در یک خط: «عنوان: مقدار»",
                                          bold=True, wrap=True))
        self.specs = QPlainTextEdit(specs_to_text(self.item.get("specs")))
        self.specs.setPlaceholderText("نمایشگر: 6.7 اینچ AMOLED" + NL + "باتری: 5000 میلی‌آمپر ساعت")
        self.specs.setMinimumHeight(110)
        self.root.addWidget(self.specs)
        self.root.addWidget(widgets.label(
            "عکس‌ها خودکار به اندازهٔ سایت (۱۲۸۰×۱۰۲۴، زمینهٔ روشن) درمی‌آیند. قیمت هیچ‌وقت در "
            "سایت نوشته نمی‌شود.", name="Muted", wrap=True))
        self.finish()

    def _auto_code(self, text: str) -> None:
        taken = {i["code"] for i in self.store.items()}
        self.code.setText(cat.code_from_name(text, taken) if text.strip() else "")

    def _add_color_row(self, name: str, image: str) -> None:
        row = self.colors.rowCount()
        self.colors.insertRow(row)
        self.colors.setItem(row, 0, QTableWidgetItem(name))
        status = QTableWidgetItem("دارد" if image and self.store.has_photo(image) else "ندارد")
        status.setFlags(status.flags() & ~Qt.ItemFlag.ItemIsEditable)
        status.setData(Qt.ItemDataRole.UserRole, image)
        self.colors.setItem(row, 1, status)

    def _new_color(self) -> None:
        self._add_color_row("", "")
        self.colors.setCurrentCell(self.colors.rowCount() - 1, 0)
        self.colors.editItem(self.colors.item(self.colors.rowCount() - 1, 0))

    def _current_row(self) -> int:
        row = self.colors.currentRow()
        if row < 0:
            self.error_label.setText("اول یک رنگ را در جدول انتخاب کنید.")
        return row

    def _color_photo(self) -> None:
        row = self._current_row()
        if row < 0:
            return
        data = read_photo(self)
        if data is not None:
            self._photos[row] = data
            self.colors.item(row, 1).setText("تازه")

    def _remove_color(self) -> None:
        row = self._current_row()
        if row < 0:
            return
        self.colors.removeRow(row)
        self._photos = {(r if r < row else r - 1): d for r, d in self._photos.items() if r != row}

    def _card_photo(self) -> None:
        data = read_photo(self)
        if data is not None:
            self._card = data
            self._show_card()

    def _show_card(self) -> None:
        if self._card is not None:
            self.card_label.setText("عکس کارت: تازه انتخاب شد.")
        elif self.item.get("image") and self.store.has_photo(self.item["image"]):
            self.card_label.setText("عکس کارت: دارد.")
        else:
            self.card_label.setText("عکس کارت: ندارد (عکس رنگ اول نشان داده می‌شود).")

    def value(self) -> dict:
        code = self.code.text().strip().lower()
        colors = []
        for row in range(self.colors.rowCount()):
            name = (self.colors.item(row, 0).text() if self.colors.item(row, 0) else "").strip()
            if not name:
                continue
            image = self.colors.item(row, 1).data(Qt.ItemDataRole.UserRole) or ""
            if row in self._photos:
                image = cat.photo_name(code, name)
            colors.append({"name": name, "image": image,
                           "hex": next((c.get("hex", "") for c in self.item.get("colors") or []
                                        if c.get("name") == name), "")})
        image = self.item.get("image") or ""
        if self._card is not None:
            image = cat.photo_name(code)
        return {**self.item, "code": code, "category": cat.KIND_PHONE,
                "brand": self.brand.currentData() or "", "name": self.name.text().strip(),
                "tier": self.tier.currentText().strip(), "release_year": self.year.value(),
                "colors": colors, "specs": parse_specs_text(self.specs.toPlainText()),
                "image": image, "hidden": bool(self.item.get("hidden"))}

    def _save(self) -> None:
        item = self.value()
        try:
            notes = []
            # check first, then store the photos, then the item
            problems = cat.item_problems(cat.clean_item(item), self.store.brand_keys())
            if problems:
                raise SiteDataError(" ".join(problems))
            for row, data in self._photos.items():
                name = (self.colors.item(row, 0).text() or "").strip()
                if name:
                    notes += self.store.add_photo(cat.photo_name(item["code"], name), data)
            if self._card is not None:
                notes += self.store.add_photo(cat.photo_name(item["code"]), self._card)
            self.saved = self.store.upsert(item, old_code=self.item.get("code", ""))
        except (SiteDataError, ph.PhotoError) as exc:
            self.error_label.setText(str(exc))
            return
        if notes:
            widgets.info(self, "عکس", NL.join(dict.fromkeys(notes)), kind="warning")
        self.accept()


# ---- accessory -----------------------------------------------------------------------
class AccessoryDialog(_FormDialog):
    """لوازم جانبی: عکس، عنوان، نوع، مشخصات، توضیح."""

    def __init__(self, store: SiteStore, item: Optional[dict] = None,
                 parent: QWidget | None = None) -> None:
        self.item = dict(item or {})
        self.new = item is None
        super().__init__(store, "افزودن لوازم جانبی" if self.new else "ویرایش لوازم جانبی", parent)
        self.name = QLineEdit(self.item.get("name", ""))
        self.name.setPlaceholderText("مثلاً پاوربانک انکر ۲۰ هزار")
        self.name.setMaxLength(120)
        self.row("عنوان:", self.name)
        self.group = QComboBox()
        for key, title in cat.GROUPS.items():
            self.group.addItem(title, key)
        self.group.setCurrentIndex(max(0, self.group.findData(self.item.get("group") or "other")))
        self.row("نوع:", self.group)
        self.brand_name = QLineEdit(self.item.get("brand_name", ""))
        self.brand_name.setPlaceholderText("اختیاری، مثلاً Anker")
        self.brand_name.setMaxLength(40)
        self.row("برند:", self.brand_name)
        self._photo: Optional[bytes] = None
        photo_row = QHBoxLayout()
        photo_row.addWidget(widgets.button("انتخاب عکس…", icon_name="image",
                                           on_click=self._pick_photo))
        self.photo_label = widgets.label("", name="Muted", wrap=True)
        photo_row.addWidget(self.photo_label, 1)
        self.root.addLayout(photo_row)
        self._show_photo()
        self.root.addWidget(widgets.label("مشخصات — هر مورد در یک خط: «عنوان: مقدار»",
                                          bold=True, wrap=True))
        self.specs = QPlainTextEdit(specs_to_text(self.item.get("specs")))
        self.specs.setMinimumHeight(90)
        self.root.addWidget(self.specs)
        self.root.addWidget(widgets.label("توضیح کوتاه:", bold=True))
        self.description = QPlainTextEdit(self.item.get("description", ""))
        self.description.setMinimumHeight(70)
        self.root.addWidget(self.description)
        self.finish()

    def _pick_photo(self) -> None:
        data = read_photo(self)
        if data is not None:
            self._photo = data
            self._show_photo()

    def _show_photo(self) -> None:
        if self._photo is not None:
            self.photo_label.setText("عکس تازه انتخاب شد.")
        elif self.item.get("image") and self.store.has_photo(self.item["image"]):
            self.photo_label.setText("عکس دارد.")
        else:
            self.photo_label.setText("عکس ندارد (نماد نوع کالا نشان داده می‌شود).")

    def value(self) -> dict:
        code = self.item.get("code") or cat.code_from_name(
            self.name.text() or "accessory", {i["code"] for i in self.store.items()})
        if not cat.valid_code(code):
            code = cat.code_from_name("accessory", {i["code"] for i in self.store.items()})
        image = self.item.get("image") or ""
        if self._photo is not None:
            image = cat.photo_name(code)
        return {**self.item, "code": code, "category": cat.KIND_ACCESSORY,
                "name": self.name.text().strip(), "group": self.group.currentData() or "other",
                "brand_name": self.brand_name.text().strip(),
                "specs": parse_specs_text(self.specs.toPlainText()),
                "description": " ".join(self.description.toPlainText().split()),
                "image": image, "colors": [], "hidden": bool(self.item.get("hidden"))}

    def _save(self) -> None:
        item = self.value()
        try:
            problems = cat.item_problems(cat.clean_item(item), self.store.brand_keys())
            if problems:
                raise SiteDataError(" ".join(problems))
            if self._photo is not None:
                self.store.add_photo(item["image"], self._photo)
            self.saved = self.store.upsert(item, old_code=self.item.get("code", ""))
        except (SiteDataError, ph.PhotoError) as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()


# ---- accessory PDF (optional helper) ----------------------------------------------------
class AccessoryPdfDialog(widgets.ResponsiveDialog):
    """کالاهای یک PDF لوازم جانبی؛ تیک‌خورده‌ها اضافه می‌شوند (روی همین رایانه)."""

    def __init__(self, store: SiteStore, data: bytes, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from ..site import accessory_pdf

        self.store = store
        self.added = 0
        self.setWindowTitle("لوازم جانبی از PDF")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(580)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(widgets.label("کالاهای این PDF", size=15, bold=True))
        root.addWidget(widgets.label(
            "هر کالایی را که درست خوانده شده تیک بزنید؛ با عنوان، مشخصات و عکسش اضافه می‌شود و "
            "بعد می‌توانید آن را ویرایش کنید.", name="Muted", wrap=True))
        self.list = QListWidget()
        self.list.setMinimumHeight(240)
        root.addWidget(self.list)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        root.addWidget(self.error_label)
        self.add_button = widgets.button("افزودن تیک‌خورده‌ها", icon_name="plus",
                                         variant="primary", on_click=self._add)
        root.addLayout(widgets.footer(self.add_button,
                                      close=widgets.button("انصراف", on_click=self.reject)))
        self.items = []
        try:
            self.items = accessory_pdf.read_pdf(
                data, taken_codes={i["code"] for i in store.items()})
        except ValueError as exc:
            self.error_label.setText(str(exc))
        for item in self.items:
            text = (f"{item.name} — {cat.GROUPS.get(item.group, 'سایر')} — "
                    f"{format_int(len(item.specs))} مشخصه، {format_int(len(item.images))} عکس — "
                    f"صفحهٔ {to_persian_digits(item.page)}")
            entry = QListWidgetItem(text)
            entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            entry.setCheckState(Qt.CheckState.Checked)
            entry.setToolTip(NL.join(f"{k}: {v}" for k, v in item.specs))
            self.list.addItem(entry)
        if not self.items and not self.error_label.text():
            self.error_label.setText("کالایی در این PDF پیدا نشد.")
        self.add_button.setEnabled(bool(self.items))

    def _add(self) -> None:
        from ..site import accessory_pdf

        chosen = [item for n, item in enumerate(self.items)
                  if self.list.item(n).checkState() == Qt.CheckState.Checked]
        if not chosen:
            self.error_label.setText("هیچ کالایی تیک نخورده است.")
            return
        for item in chosen:
            image = ""
            if item.images:
                image = cat.photo_name(item.code)
                try:
                    self.store.add_photo(image, item.images[0])
                except (ph.PhotoError, SiteDataError):
                    image = ""
            try:
                self.store.upsert(accessory_pdf.item_for(item, image))
                self.added += 1
            except SiteDataError:
                continue
        self.accept()
