"""v2.14.0 «افزودن از PDF» — پیش‌نمایش پیش از ذخیره، برای همان شاخه‌ای که انتخاب شده.

* هر ردیف جدول PDF = یک کالا، با عکس همان ردیف (بی‌عکس‌ها با «عکس ندارد» مشخص‌اند)؛
* عنوان در جدول ویرایش‌پذیر است؛ «ویرایش» برای عنوان، مشخصات و توضیح؛ «حذف» ردیف را
  از این ورود کنار می‌گذارد؛
* ردیف «نزدیک» (چند حرف فرق) کنار کالای موجود با هر دو عکس دیده می‌شود: «یکی است» یا
  «جداست» — بی‌تصمیم ذخیره نمی‌شود؛
* بالای جدول: تازه / به‌روزرسانی / تکراری / منتظر تصمیم / بی‌عکس.
قیمت هیچ‌وقت خوانده‌شده نشان داده یا ذخیره نمی‌شود.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..persian import format_int
from ..site import dedup
from ..site import pdf_import as imp
from ..site import pdf_table as pt
from ..site.store import SiteStore
from . import theme, widgets
from .site_dialogs import parse_specs_text, specs_to_text

NL = chr(10)
HEADERS = ("عکس", "عنوان", "مشخصات", "برند / رنگ", "وضعیت", "کالای مشابه در سایت", "")
THUMB = 56
STATUS_FA = {dedup.NEW: ("تازه", "success"), dedup.UPDATED: ("به‌روزرسانی", "info"),
             dedup.DUPLICATE: ("تکراری", "neutral"), dedup.NEAR: ("نزدیک — تصمیم با شما", "warning")}


def read_rows(data: bytes) -> list[pt.TableRow]:
    """Table rows of the PDF; a PDF without a table falls back to the older
    title-and-specs reader (one candidate = one row). Raises ValueError (Persian)."""
    try:
        return pt.read_table_pdf(data)
    except ValueError as exc:
        if "جدولی" not in str(exc):
            raise
    from ..site import accessory_pdf

    rows = []
    for found in accessory_pdf.read_pdf(data):
        rows.append(pt.TableRow(page=found.page, name=found.name, brand_name=found.brand_name,
                                specs=found.specs, image=found.images[0] if found.images else None,
                                notes=[] if found.images else ["عکس ندارد"]))
    return rows


def summary_text(rows: list[imp.Prepared]) -> str:
    counts = imp.summary(rows)
    parts = [f"تازه: {format_int(counts[dedup.NEW])}",
             f"به‌روزرسانی: {format_int(counts[dedup.UPDATED])}",
             f"تکراری: {format_int(counts[dedup.DUPLICATE])}"]
    if counts[dedup.NEAR]:
        parts.append(f"منتظر تصمیم («یکی است/جداست»): {format_int(counts[dedup.NEAR])}")
    if counts["no_image"]:
        parts.append(f"بی‌عکس: {format_int(counts['no_image'])}")
    if counts["removed"]:
        parts.append(f"کنار گذاشته: {format_int(counts['removed'])}")
    return "، ".join(parts)


def _pixmap(data: Optional[bytes] = None, path=None) -> QPixmap:
    pixmap = QPixmap()
    if data:
        pixmap.loadFromData(data)
    elif path is not None and path.is_file():
        pixmap.load(str(path))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


def _thumb(pixmap: QPixmap, missing: str = "عکس ندارد") -> QLabel:
    holder = QLabel()
    holder.setAlignment(Qt.AlignmentFlag.AlignCenter)
    holder.setMinimumSize(THUMB + 8, THUMB + 8)
    if pixmap.isNull():
        holder.setText(missing)
        holder.setStyleSheet(f"color: {theme.DANGER}; font-weight: 600;")
    else:
        holder.setPixmap(pixmap)
    return holder


class RowEditDialog(widgets.ResponsiveDialog):
    """عنوان، مشخصات و توضیح یک ردیف پیش از ذخیره."""

    def __init__(self, item: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self.setWindowTitle("ویرایش ردیف")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.addWidget(widgets.label("ویرایش ردیف", size=15, bold=True))
        root.addWidget(widgets.label("عنوان:"))
        self.name = QLineEdit(item.get("name", ""))
        self.name.setMaxLength(120)
        root.addWidget(self.name)
        root.addWidget(widgets.label("برند:"))
        self.brand = QLineEdit(item.get("brand_name", ""))
        self.brand.setMaxLength(40)
        root.addWidget(self.brand)
        root.addWidget(widgets.label("مشخصات — هر مورد در یک خط: «عنوان: مقدار»", wrap=True))
        self.specs = QPlainTextEdit(specs_to_text(item.get("specs")))
        self.specs.setMinimumHeight(140)
        root.addWidget(self.specs)
        root.addWidget(widgets.label("توضیح:"))
        self.description = QPlainTextEdit(item.get("description", ""))
        self.description.setMinimumHeight(70)
        root.addWidget(self.description)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        root.addWidget(self.error_label)
        root.addLayout(widgets.footer(
            widgets.button("ذخیره", icon_name="check", variant="primary", on_click=self._save),
            close=widgets.button("انصراف", on_click=self.reject)))

    def _save(self) -> None:
        name = " ".join(self.name.text().split())
        if not name:
            self.error_label.setText("عنوان را بنویسید.")
            return
        self.item.update(name=name, brand_name=" ".join(self.brand.text().split()),
                         specs=parse_specs_text(self.specs.toPlainText()),
                         description=" ".join(self.description.toPlainText().split())[:600])
        self.accept()


class PdfImportDialog(widgets.ResponsiveDialog):
    """پیش‌نمایش «افزودن از PDF» در یک دستهٔ لوازم جانبی."""

    def __init__(self, store: SiteStore, group: str, data: bytes, *, file_name: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.group = group
        self.result_counts: dict = {}
        self.rows: list[imp.Prepared] = []
        group_name = store.group_name(group)
        self.setWindowTitle(f"افزودن از PDF — {group_name}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(980)
        self.setMinimumHeight(560)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(widgets.label(f"افزودن از PDF به «{group_name}»", size=15, bold=True))
        if file_name:
            root.addWidget(widgets.label(file_name, name="Muted", wrap=True))
        root.addWidget(widgets.label(
            "هر ردیف جدول یک کالاست و عکس همان ردیف را دارد. عنوان را می‌شود همین‌جا عوض کرد؛ "
            "«ویرایش» برای مشخصات و «حذف» برای کنار گذاشتن یک ردیف. قیمت خوانده نمی‌شود و در "
            "سایت نمی‌آید.", name="Muted", wrap=True))
        self.summary = widgets.label("", bold=True, wrap=True)
        root.addWidget(self.summary)
        self.table = QTableWidget(0, len(HEADERS))
        widgets.round_view_corners(self.table)
        self.table.setHorizontalHeaderLabels(list(HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(THUMB + 14)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, THUMB + 16)
        self.table.setColumnWidth(1, 300)
        self.table.setColumnWidth(2, 200)
        self.table.setColumnWidth(3, 140)
        self.table.setColumnWidth(4, 170)
        self.table.setColumnWidth(5, 260)
        self.table.setColumnWidth(6, 260)
        self.table.itemChanged.connect(self._title_edited)
        root.addWidget(self.table, 1)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        root.addWidget(self.error_label)
        self.save_button = widgets.button("ذخیره در سایت (روی همین رایانه)", icon_name="check",
                                          variant="primary", on_click=self._save)
        root.addLayout(widgets.footer(self.save_button,
                                      close=widgets.button("انصراف", on_click=self.reject)))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.rows = imp.prepare(store, group, read_rows(data))
        except ValueError as exc:
            self.error_label.setText(str(exc))
        finally:
            QApplication.restoreOverrideCursor()
        if not self.rows and not self.error_label.text():
            self.error_label.setText("کالایی در این PDF پیدا نشد.")
        self._fill()

    # ---- table -----------------------------------------------------------------------
    def _fill(self) -> None:
        self._filling = True
        table = self.table
        table.setRowCount(0)
        for index, prepared in enumerate(self.rows):
            table.insertRow(index)
            item = prepared.item
            table.setCellWidget(index, 0, _thumb(_pixmap(prepared.row.image)))
            title = QTableWidgetItem(item["name"])
            title.setToolTip(prepared.row.raw_title or item["name"])
            table.setItem(index, 1, title)
            specs = QTableWidgetItem("، ".join(f"{k}: {v}" for k, v in item["specs"][:3]))
            specs.setToolTip(specs_to_text(item["specs"]) + (NL + NL + item["description"]
                                                             if item["description"] else ""))
            specs.setFlags(specs.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(index, 2, specs)
            colors = "، ".join(c["name"] for c in item["colors"])
            brand = QTableWidgetItem(" / ".join(p for p in (item["brand_name"], colors) if p) or "—")
            brand.setFlags(brand.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(index, 3, brand)
            table.setCellWidget(index, 4, self._status_cell(prepared))
            table.setCellWidget(index, 5, self._match_cell(index, prepared))
            table.setCellWidget(index, 6, self._actions_cell(index, prepared))
        self._filling = False
        self.summary.setText(summary_text(self.rows))
        self.save_button.setEnabled(any(not r.removed for r in self.rows))

    def _status_cell(self, prepared: imp.Prepared) -> QWidget:
        if prepared.removed:
            text, status = "کنار گذاشته", "neutral"
        elif prepared.match.status == dedup.NEAR and prepared.decision:
            text, status = ("یکی است" if prepared.decision == imp.SAME else "جداست"), "info"
        else:
            text, status = STATUS_FA[prepared.match.status]
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(4, 2, 4, 2)
        box.addWidget(widgets.StatusPill(text, status))
        if prepared.row.image is None:
            box.addWidget(widgets.label("عکس ندارد", color=theme.DANGER))
        return holder

    def _match_cell(self, index: int, prepared: imp.Prepared) -> QWidget:
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(4, 2, 4, 2)
        other = prepared.match.other
        if other is None or prepared.match.status not in (dedup.NEAR, dedup.UPDATED,
                                                          dedup.DUPLICATE):
            line.addWidget(widgets.label("—", name="Muted"))
            return holder
        image = other.get("image") or ""
        line.addWidget(_thumb(_pixmap(path=self.store.photo_path(image) if image else None), "—"))
        line.addWidget(widgets.label(other.get("name", ""), wrap=True), 1)
        if prepared.match.status == dedup.NEAR and not prepared.removed:
            column = QVBoxLayout()
            same = widgets.button("یکی است", on_click=lambda: self._decide(index, imp.SAME))
            apart = widgets.button("جداست", on_click=lambda: self._decide(index, imp.SEPARATE))
            for b in (same, apart):
                b.setMinimumWidth(b.sizeHint().width())
                column.addWidget(b)
            line.addLayout(column)
        return holder

    def _actions_cell(self, index: int, prepared: imp.Prepared) -> QWidget:
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(4, 2, 4, 2)
        for b in (widgets.button("ویرایش", icon_name="edit", on_click=lambda: self._edit(index)),
                  widgets.button("بازگرداندن" if prepared.removed else "حذف",
                                 icon_name="refresh" if prepared.removed else "trash",
                                 on_click=lambda: self._remove(index))):
            b.setMinimumWidth(b.sizeHint().width())      # never cut (text_fit_audit)
            line.addWidget(b)
        return holder

    def _keep_scroll(self, change) -> None:
        bar = self.table.verticalScrollBar()
        value = bar.value()
        change()
        self._fill()
        bar.setValue(value)
        self.table.selectRow(min(self._current, self.table.rowCount() - 1))

    def _decide(self, index: int, decision: str) -> None:
        self._current = index
        self._keep_scroll(lambda: setattr(self.rows[index], "decision", decision))

    def _remove(self, index: int) -> None:
        self._current = index
        self._keep_scroll(lambda: setattr(self.rows[index], "removed", not self.rows[index].removed))

    def _edit(self, index: int) -> None:
        self._current = index
        if RowEditDialog(self.rows[index].item, parent=self).exec():
            self._keep_scroll(lambda: None)

    def _title_edited(self, cell: QTableWidgetItem) -> None:
        if getattr(self, "_filling", False) or cell.column() != 1:
            return
        name = " ".join(cell.text().split())
        if name:
            self.rows[cell.row()].item["name"] = name[:120]

    # ---- save ------------------------------------------------------------------------
    def _save(self) -> None:
        waiting = imp.undecided(self.rows)
        if waiting and not widgets.confirm(
                self, "ردیف‌های نزدیک",
                f"{format_int(waiting)} ردیف شبیه کالای موجود است و هنوز «یکی است» یا «جداست» "
                "نخورده؛ این ردیف‌ها ذخیره نمی‌شوند. بقیه ذخیره شود؟", confirm_text="ذخیره"):
            return
        empty = [n for n, r in enumerate(self.rows) if not r.removed and not r.item["name"].strip()]
        if empty:
            self.error_label.setText("ردیفی بدون عنوان هست؛ عنوانش را بنویسید یا «حذف» بزنید.")
            return
        self.result_counts = imp.apply(self.store, self.group, self.rows)
        self.accept()

    def result_text(self) -> str:
        c = self.result_counts
        return (f"{format_int(c.get('new', 0))} کالای تازه، {format_int(c.get('updated', 0))} "
                f"به‌روزرسانی، {format_int(c.get('duplicate', 0))} تکراری (بی‌تغییر)"
                + (f"، {format_int(c['skipped'])} ذخیره نشد" if c.get("skipped") else "") + ".")

    _current = 0
    _filling = False
