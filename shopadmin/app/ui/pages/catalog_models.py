"""صفحهٔ «مدل‌های سایت» — نگاشت کد مدل دائمی سایت (slug) به کالاهای حسابداری (§9a).

* مدل‌ها از فایل ``products.js`` سایت وارد می‌شوند (کد مدل، نام، برند، نام‌های دیگر).
* برای هر مدل، کالاهای حسابداری با جستجوی فازی پیشنهاد می‌شوند و مالک یک‌بار تأیید می‌کند.
* بررسی شبانه: تغییر کوچک نام = «نام تغییرکرده» (مدل نمایش داده می‌شود)؛ کالای گم‌شده یا
  تغییر بزرگ نام = مدل تا «تأیید» پنهان می‌شود و هشدار بله می‌رود.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...persian import format_int, format_shamsi, to_persian_digits
from ...permissions import CATALOG_MANAGE
from .. import theme, widgets
from ..base_page import BasePage

NL = chr(10)
MODEL_HEADERS = ("برند", "مدل", "کد مدل", "وضعیت", "کالاها")
ITEM_HEADERS = ("کد کالا", "برچسب برای مشتری", "نام تأییدشده", "نام فعلی در حسابداری", "وضعیت",
                "شباهت", "ردیف لیست قیمت")

FILTERS = (
    ("review", "پنهان (منتظر تأیید)"),
    ("drifted", "نام تغییرکرده"),
    ("unmapped", "نگاشت‌نشده"),
    ("ok", "فعال"),
    ("all", "همه"),
)
STATUS_FA = {"ok": "فعال", "review": "پنهان — منتظر تأیید", "unmapped": "نگاشت‌نشده"}
STATUS_COLOR = {"ok": "success", "review": "danger", "unmapped": "warning"}
ITEM_STATE_FA = {"ok": "درست", "drifted": "نام تغییرکرده", "missing": "پیدا نشد / تغییر زیاد"}
ITEM_STATE_COLOR = {"ok": theme.SUCCESS_DARK, "drifted": theme.WARNING_TEXT, "missing": theme.DANGER}

_BRAND_RE = re.compile(r'^\s*name:\s*"([^"]+)",\s*mark:', re.MULTILINE)
_ITEM_RE = re.compile(r'\{\s*id:\s*"([^"]+)",\s*name:\s*"([^"]+)"')
_ALIASES_RE = re.compile(r'aliases:\s*\[([^\]]*)\]')
_STRING_RE = re.compile(r'"([^"]*)"')


# ---- pure helpers (tested without a window) ----------------------------------------
def parse_products_js(text: str) -> list[dict]:
    """Models of the site's ``assets/products.js``: [{slug, name, brand, aliases}].

    Read as text (never executed): each item starts with ``{ id: "…", name: "…"``;
    its brand is the closest ``name: "…", mark:`` line above it.
    """
    brands = [(m.start(), m.group(1)) for m in _BRAND_RE.finditer(text)]
    items = list(_ITEM_RE.finditer(text))
    out = []
    for n, match in enumerate(items):
        end = items[n + 1].start() if n + 1 < len(items) else len(text)
        segment = text[match.end():end]
        aliases_match = _ALIASES_RE.search(segment)
        aliases = _STRING_RE.findall(aliases_match.group(1)) if aliases_match else []
        brand = ""
        for pos, name in brands:
            if pos < match.start():
                brand = name
        out.append({"slug": match.group(1), "name": match.group(2), "brand": brand,
                    "aliases": [a for a in aliases if a.strip()][:30]})
    return out


def model_matches(model: dict, key: str, text: str = "") -> bool:
    if key == "drifted" and not model.get("drifted_count"):
        return False
    if key in ("review", "unmapped", "ok") and model.get("status") != key:
        return False
    needle = _norm(text)
    if not needle:
        return True
    haystack = _norm(" ".join(str(model.get(k) or "") for k in ("name", "slug", "brand", "aliases")))
    return all(part in haystack for part in needle.split())


def _norm(text: str) -> str:
    return " ".join(str(text or "").replace("ي", "ی").replace("ك", "ک").lower().split())


def score_fa(score) -> str:
    if score is None:
        return "—"
    return to_persian_digits(f"{round(float(score) * 100)}٪")


def filter_label(key: str, counts: dict) -> str:
    title = dict(FILTERS)[key]
    count = counts.get(key)
    return f"{title} ({to_persian_digits(count)})" if count is not None else title


def check_summary_fa(last: Optional[dict]) -> str:
    if not last:
        return "بررسی شبانه هنوز اجرا نشده است."
    hidden = last.get("newly_hidden") or []
    text = (f"آخرین بررسی: {format_shamsi(last.get('at'))} — "
            f"{format_int(last.get('checked') or 0)} کالا، "
            f"{format_int(last.get('drifted') or 0)} نام تغییرکرده، "
            f"{format_int(last.get('missing') or 0)} پیدا نشد")
    if hidden:
        text += f"؛ {format_int(len(hidden))} مدل پنهان شد"
    return text


class CatalogModelsPage(BasePage):
    title = "مدل‌های سایت"
    subtitle = ("نگاشت «کد مدل» سایت به کالاهای حسابداری — ربات فقط مدل‌های تأییدشده را "
                "به مشتری نشان می‌دهد")

    def build_body(self) -> None:
        self.can_manage = self.context.can(CATALOG_MANAGE)
        self._models: list[dict] = []
        self._counts: dict = {}
        self._detail: Optional[dict] = None
        self._items: list[dict] = []
        self._selected_id: Optional[int] = None

        self.banner = widgets.label("", wrap=True)
        self.body.addWidget(self.banner)

        bar_holder = QWidget()
        bar = widgets.FlowLayout(bar_holder, spacing=10)
        self.filter_combo = QComboBox()
        for key, title in FILTERS:
            self.filter_combo.addItem(title, key)
        self.filter_combo.setCurrentIndex(self.filter_combo.findData("all"))
        self.filter_combo.currentIndexChanged.connect(lambda _i: self._render_models())
        bar.addWidget(self._labeled("نمایش:", self.filter_combo))
        self.search = widgets.SearchBox("جستجوی مدل، کد مدل یا برند…")
        self.search.textChanged.connect(lambda _t: self._render_models())
        bar.addWidget(self.search)
        self.import_button = widgets.button("ورود مدل‌ها از سایت…", icon_name="download",
                                            on_click=self._import_file,
                                            tooltip="فایل assets/products.js سایت را انتخاب کنید.")
        self.check_button = widgets.button("بررسی اکنون", icon_name="refresh",
                                           on_click=self._check_now,
                                           tooltip="همان بررسی شبانه، همین حالا.")
        for b in (self.import_button, self.check_button):
            b.setEnabled(self.can_manage)
            bar.addWidget(b)
        self.body.addWidget(bar_holder)

        models_panel = widgets.Panel()
        self.models_table = widgets.DataTable(MODEL_HEADERS, selectable_rows=True,
                                              key="catalog_models")
        self.models_table.set_empty_state(
            "مدلی نیست", "با «ورود مدل‌ها از سایت» فایل products.js را وارد کنید.", "file")
        self.models_table.setMinimumHeight(260)
        self.models_table.itemSelectionChanged.connect(self._on_model_selected)
        models_panel.body.addWidget(self.models_table, 1)
        self.models_summary = widgets.label("", name="Muted")
        models_panel.body.addWidget(self.models_summary)
        self.body.addWidget(models_panel, 1)

        detail_panel = widgets.Panel()
        self.detail_title = widgets.label("یک مدل را انتخاب کنید.", size=13, bold=True, wrap=True)
        detail_panel.body.addWidget(self.detail_title)
        self.detail_hint = widgets.label("", name="Muted", wrap=True)
        detail_panel.body.addWidget(self.detail_hint)
        self.items_table = widgets.DataTable(ITEM_HEADERS, selectable_rows=True,
                                             key="catalog_items")
        self.items_table.set_empty_state("کالایی نگاشت نشده",
                                         "«افزودن کالا» پیشنهادهای حسابداری را نشان می‌دهد.", "link")
        self.items_table.setMinimumHeight(180)
        self.items_table.row_activated.connect(lambda _r: self._replace_item())
        detail_panel.body.addWidget(self.items_table, 1)

        actions_holder = QWidget()
        actions = widgets.FlowLayout(actions_holder, spacing=8)
        self.add_button = widgets.button("افزودن کالا…", icon_name="plus", variant="primary",
                                         on_click=self._add_item)
        self.replace_button = widgets.button("جایگزینی کالا…", icon_name="link",
                                             on_click=self._replace_item)
        self.accept_button = widgets.button("پذیرش نام فعلی", icon_name="check",
                                            on_click=self._accept_item)
        self.label_button = widgets.button("برچسب…", icon_name="edit", on_click=self._edit_label)
        self.delete_button = widgets.button("حذف کالا", icon_name="trash",
                                            on_click=self._delete_item)
        self.aliases_button = widgets.button("نام‌های دیگر…", icon_name="edit",
                                             on_click=self._edit_aliases)
        self.confirm_button = widgets.button("تأیید و نمایش به مشتری", icon_name="eye",
                                             variant="success", on_click=self._confirm_model)
        self._detail_buttons = (self.add_button, self.replace_button, self.accept_button,
                                self.label_button, self.delete_button, self.aliases_button,
                                self.confirm_button)
        for b in self._detail_buttons:
            b.setEnabled(False)
            actions.addWidget(b)
        detail_panel.body.addWidget(actions_holder)
        self.body.addWidget(detail_panel, 1)

    @staticmethod
    def _labeled(text: str, widget: QWidget) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(widgets.label(text))
        row.addWidget(widget)
        return box

    def set_filter(self, key: str) -> None:
        index = self.filter_combo.findData(key)
        if index >= 0:
            self.filter_combo.setCurrentIndex(index)

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        self.models_table.set_busy(True)
        self.run(lambda: self.context.api.list_catalog_models(),
                 on_success=self._on_models, on_error=self._models_error)

    def _models_error(self, message: str, kind: str) -> None:
        self.models_table.set_busy(False)
        self.models_table.fill([])
        self.models_table.set_error_state(hint=message)
        self.default_error(message, kind)

    def _on_models(self, payload: dict) -> None:
        self.models_table.set_busy(False)
        self._models = list(payload.get("models") or [])
        self._counts = dict(payload.get("counts") or {})
        for i, (key, _title) in enumerate(FILTERS):
            self.filter_combo.setItemText(i, filter_label(key, self._counts))
        self._update_banner(payload.get("last_check"))
        self._render_models()
        if self._selected_id is not None:
            self._load_detail(self._selected_id)

    def _update_banner(self, last: Optional[dict]) -> None:
        lines = [check_summary_fa(last)]
        review = self._counts.get("review") or 0
        unmapped = self._counts.get("unmapped") or 0
        if review:
            lines.append(f"{to_persian_digits(review)} مدل از دید مشتری پنهان است تا آن را "
                         "بررسی و «تأیید» کنید.")
        if unmapped:
            lines.append(f"{to_persian_digits(unmapped)} مدل هنوز به کالای حسابداری نگاشت "
                         "نشده است (ربات برای آن‌ها تلفن فروشگاه را می‌دهد).")
        self.banner.setText(NL.join(lines))
        color = theme.DANGER if review else theme.WARNING_TEXT if unmapped else theme.SUCCESS_DARK
        self.banner.setStyleSheet(f"color: {color}; font-weight: 600;")

    def _visible_models(self) -> list[dict]:
        key = self.filter_combo.currentData() or "all"
        text = self.search.text()
        return [m for m in self._models if model_matches(m, key, text)]

    def _render_models(self) -> None:
        models = self._visible_models()
        table = self.models_table
        table.blockSignals(True)
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(0)
            for m in models:
                i = table.rowCount()
                table.insertRow(i)
                table.set_cell(i, 0, str(m.get("brand") or "—"))
                table.set_cell(i, 1, str(m.get("name") or ""), bold=True)
                table.set_cell(i, 2, str(m.get("slug") or ""))
                status = str(m.get("status") or "")
                text = STATUS_FA.get(status, status)
                if status == "ok" and m.get("drifted_count"):
                    text += " (نام تغییرکرده)"
                table.set_widget(i, 3, widgets.pill_cell(widgets.StatusPill(
                    text, STATUS_COLOR.get(status, ""))))
                table.set_cell(i, 4, format_int(m.get("item_count") or 0))
                if m.get("id") == self._selected_id:
                    table.selectRow(i)
        finally:
            table.setUpdatesEnabled(True)
            table.blockSignals(False)
        table._refresh_states()
        self.models_summary.setText(f"{format_int(len(models))} مدل")

    def _on_model_selected(self) -> None:
        rows = sorted({index.row() for index in self.models_table.selectionModel().selectedRows()})
        models = self._visible_models()
        if len(rows) != 1 or not 0 <= rows[0] < len(models):
            return
        model_id = int(models[rows[0]]["id"])
        if model_id != self._selected_id or self._detail is None:
            self._selected_id = model_id
            self._load_detail(model_id)

    def _load_detail(self, model_id: int) -> None:
        self.run(lambda: self.context.api.catalog_model(model_id), on_success=self._on_detail)

    def _on_detail(self, payload: dict) -> None:
        self._detail = dict(payload.get("model") or {})
        self._items = list(payload.get("items") or [])
        model = self._detail
        status = str(model.get("status") or "")
        self.detail_title.setText(f"{model.get('name')}  —  کد مدل: {model.get('slug')}  —  "
                                  f"{STATUS_FA.get(status, status)}")
        hints = []
        if status == "review":
            hints.append("این مدل پنهان است. کالای «پیدا نشد» را جایگزین یا حذف کنید، سپس "
                         "«تأیید و نمایش به مشتری» را بزنید.")
        if any(i.get("state") == "drifted" for i in self._items):
            hints.append("نام برخی کالاها در حسابداری کمی تغییر کرده؛ مدل نمایش داده می‌شود. "
                         "اگر درست است «پذیرش نام فعلی» را بزنید.")
        if model.get("aliases"):
            hints.append("نام‌های دیگر: " + "، ".join(str(model["aliases"]).splitlines()))
        self.detail_hint.setText(NL.join(hints))
        self._render_items()
        for b in self._detail_buttons:
            b.setEnabled(self.can_manage)
        self.confirm_button.setEnabled(self.can_manage and status == "review")

    def _render_items(self) -> None:
        table = self.items_table
        table.setRowCount(0)
        for item in self._items:
            i = table.rowCount()
            table.insertRow(i)
            state = str(item.get("state") or "ok")
            table.set_cell(i, 0, to_persian_digits(item.get("kala_code")), bold=True)
            table.set_cell(i, 1, str(item.get("label") or "—"))
            table.set_cell(i, 2, str(item.get("confirmed_name") or ""))
            current = str(item.get("current_name") or "")
            table.set_cell(i, 3, current if state != "ok" else "—",
                           color=ITEM_STATE_COLOR.get(state) if state != "ok" else None)
            table.set_cell(i, 4, ITEM_STATE_FA.get(state, state), bold=True,
                           color=ITEM_STATE_COLOR.get(state))
            table.set_cell(i, 5, score_fa(item.get("score")) if state != "ok" else "—")
            table.set_cell(i, 6, format_int(item.get("pricelist_rows") or 0))
        table._refresh_states()

    # ------------------------------------------------------------------ actions
    def _one_item(self) -> Optional[dict]:
        rows = sorted({index.row() for index in self.items_table.selectionModel().selectedRows()})
        if len(rows) != 1 or not 0 <= rows[0] < len(self._items):
            self.notify_warning("یک کالا را در جدول پایین انتخاب کنید.")
            return None
        return self._items[rows[0]]

    def _after_change(self, message: str):
        def done(payload: dict) -> None:
            self.notify_success(message)
            self._on_detail(payload)
            self.load()
        return done

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "فایل products.js سایت", "",
                                              "products.js (*.js)")
        if path:
            self.import_from_path(path)

    def import_from_path(self, path: str) -> None:
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            self.notify_error("فایل خوانده نشد.")
            return
        models = parse_products_js(text)
        if not models:
            self.notify_error("مدلی در این فایل پیدا نشد؛ فایل assets/products.js سایت را انتخاب کنید.")
            return

        def done(result: dict) -> None:
            self.notify_success(
                f"{format_int(len(models))} مدل خوانده شد: {format_int(result.get('added') or 0)} "
                f"جدید، {format_int(result.get('updated') or 0)} به‌روز شد.")
            self.load()

        self.run(lambda: self.context.api.import_catalog_models(models), on_success=done,
                 busy_message="در حال ورود مدل‌ها…")

    def _check_now(self) -> None:
        def done(summary: dict) -> None:
            hidden = summary.get("newly_hidden") or []
            if hidden:
                widgets.info(self, "نتیجهٔ بررسی", check_summary_fa(summary), kind="warning",
                             detail="مدل‌های پنهان‌شده: " + "، ".join(hidden))
            else:
                self.notify_success(check_summary_fa(summary))
            self.load()

        self.run(lambda: self.context.api.check_catalog_models(), on_success=done,
                 busy_message="در حال بررسی کالاها در حسابداری…")

    def _add_item(self) -> None:
        if not self._detail:
            return
        dialog = PickProductDialog(self.context, self._detail, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        model_id, code, label = int(self._detail["id"]), dialog.kala_code, dialog.label
        self.run(lambda: self.context.api.add_catalog_item(model_id, code, label),
                 on_success=self._after_change("کالا به مدل اضافه شد."))

    def _replace_item(self) -> None:
        item = self._one_item() if self._detail else None
        if item is None or not self.can_manage:
            return
        dialog = PickProductDialog(self.context, self._detail, item=item, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        code, label = dialog.kala_code, dialog.label
        self.run(lambda: self.context.api.update_catalog_item(item["id"], kala_code=code,
                                                              label=label),
                 on_success=self._after_change("کالا جایگزین شد."))

    def _accept_item(self) -> None:
        item = self._one_item()
        if item is None:
            return
        if item.get("state") == "ok":
            self.notify_warning("نام این کالا تغییری نکرده است.")
            return
        message = (f"نام فعلی کالای {to_persian_digits(item.get('kala_code'))} در حسابداری "
                   f"«{item.get('current_name') or '—'}» است. همین کالا درست است؟")
        kind = "warning" if item.get("state") == "missing" else "info"
        if not widgets.confirm(self, "پذیرش نام فعلی", message, confirm_text="درست است",
                               kind=kind):
            return
        self.run(lambda: self.context.api.accept_catalog_item(item["id"]),
                 on_success=self._after_change("نام فعلی پذیرفته شد."))

    def _edit_label(self) -> None:
        item = self._one_item()
        if item is None:
            return
        dialog = TextDialog("برچسب برای مشتری",
                            "متن دکمه در ربات (مثلاً «۲۵۶ گیگ»)؛ خالی = نام کالا.",
                            str(item.get("label") or ""), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        label = dialog.value[:60]
        self.run(lambda: self.context.api.update_catalog_item(item["id"], label=label),
                 on_success=self._after_change("برچسب ذخیره شد."))

    def _delete_item(self) -> None:
        item = self._one_item()
        if item is None:
            return
        if not widgets.confirm(self, "حذف کالا از مدل",
                               f"کالای {to_persian_digits(item.get('kala_code'))} از این مدل حذف شود؟",
                               confirm_text="حذف", kind="warning"):
            return
        self.run(lambda: self.context.api.delete_catalog_item(item["id"]),
                 on_success=self._after_change("کالا از مدل حذف شد."))

    def _edit_aliases(self) -> None:
        if not self._detail:
            return
        dialog = TextDialog("نام‌های دیگر مدل",
                            "هر نام در یک خط؛ ربات این نام‌ها را هم می‌شناسد (مثلاً «آیفون ۱۷ پرو»).",
                            str(self._detail.get("aliases") or ""), multiline=True, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        model_id, aliases = int(self._detail["id"]), dialog.value[:1000]
        self.run(lambda: self.context.api.update_catalog_model(model_id, aliases=aliases),
                 on_success=self._after_change("نام‌های دیگر ذخیره شد."))

    def _confirm_model(self) -> None:
        if not self._detail:
            return
        if any(i.get("state") == "missing" for i in self._items):
            self.notify_warning("اول کالای «پیدا نشد» را جایگزین، حذف یا تأیید کنید.")
            return
        if not widgets.confirm(self, "تأیید مدل",
                               f"کالاهای «{self._detail.get('name')}» درست است؟ مدل دوباره به "
                               "مشتری نمایش داده می‌شود.", confirm_text="تأیید و نمایش"):
            return
        model_id = int(self._detail["id"])
        self.run(lambda: self.context.api.confirm_catalog_model(model_id),
                 on_success=self._after_change("مدل تأیید شد و دوباره نمایش داده می‌شود."))


class PickProductDialog(QDialog):
    """انتخاب کالای حسابداری برای یک مدل: پیشنهادهای فازی، جستجو یا کد مستقیم."""

    def __init__(self, context, model: dict, *, item: Optional[dict] = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.model = model
        self.item = item
        self.kala_code: int = 0
        self.label: str = str((item or {}).get("label") or "")

        self.setWindowTitle("انتخاب کالای حسابداری")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(600)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        title = f"کالای حسابداری برای «{model.get('name')}» ({model.get('slug')})"
        root.addWidget(widgets.label(title, size=14, bold=True, wrap=True))
        if item:
            root.addWidget(widgets.label(
                f"جایگزین کالای {to_persian_digits(item.get('kala_code'))} — "
                f"«{item.get('confirmed_name')}»", name="Muted", wrap=True))

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("نام کالا در حسابداری…")
        self.search.setText(str((item or {}).get("confirmed_name") or model.get("name") or ""))
        self.search.returnPressed.connect(self.load_suggestions)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(widgets.button("پیشنهاد بده", icon_name="search",
                                            on_click=self.load_suggestions))
        root.addLayout(search_row)
        self.results = QListWidget()
        self.results.setMinimumHeight(200)
        self.results.currentItemChanged.connect(self._picked)
        root.addWidget(self.results)
        root.addWidget(widgets.label(
            "پیشنهادها با مقایسهٔ نام (فارسی/انگلیسی، ی/ي، ک/ك، فاصله و رقم) مرتب شده‌اند. "
            "کالای قاب و لوازم جانبی و مدل‌های دیگر (پرو/مکس، حافظهٔ دیگر) امتیاز کم می‌گیرند.",
            name="Muted", wrap=True))

        code_row = QHBoxLayout()
        code_row.addWidget(widgets.label("کد کالا:"))
        self.code_input = QSpinBox()
        self.code_input.setRange(0, 2_000_000_000)
        self.code_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.code_input.setSpecialValueText("—")
        code_row.addWidget(self.code_input)
        code_row.addWidget(widgets.label("برچسب برای مشتری:"))
        self.label_input = QLineEdit(self.label)
        self.label_input.setPlaceholderText("مثلاً ۲۵۶ گیگ")
        self.label_input.setMaxLength(60)
        code_row.addWidget(self.label_input, 1)
        root.addLayout(code_row)

        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        root.addWidget(self.error_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(widgets.button("انصراف", on_click=self.reject))
        buttons.addWidget(widgets.button("ذخیره", icon_name="check", variant="primary",
                                         on_click=self._accept))
        root.addLayout(buttons)

        candidates = list((item or {}).get("candidates") or [])
        if candidates:
            self._fill(candidates, heading=True)
        else:
            self.load_suggestions()

    def load_suggestions(self) -> None:
        self.error_label.setText("")
        try:
            found = self.context.api.catalog_suggestions(int(self.model["id"]), self.search.text())
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.error_label.setText(str(exc))
            return
        self._fill(found)
        if not found:
            self.error_label.setText("پیشنهادی پیدا نشد؛ نام دیگری بنویسید یا کد کالا را وارد کنید.")

    def _fill(self, rows: list[dict], heading: bool = False) -> None:
        self.results.clear()
        if heading:
            head = QListWidgetItem("پیشنهادهای بررسی شبانه (با نام تأییدشدهٔ قبلی):")
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results.addItem(head)
        for row in rows:
            text = (f"{score_fa(row.get('score'))}  ·  {to_persian_digits(row.get('code'))} — "
                    f"{row.get('name') or ''}")
            if row.get("taken_by"):
                text += f"  (نگاشته به {row['taken_by']})"
            entry = QListWidgetItem(text)
            entry.setData(Qt.ItemDataRole.UserRole, int(row.get("code") or 0))
            if row.get("taken_by"):
                entry.setForeground(Qt.GlobalColor.gray)
            self.results.addItem(entry)

    def _picked(self, entry, _previous=None) -> None:
        if entry is not None and entry.data(Qt.ItemDataRole.UserRole):
            self.code_input.setValue(int(entry.data(Qt.ItemDataRole.UserRole)))

    def _accept(self) -> None:
        code = int(self.code_input.value())
        if code <= 0:
            self.error_label.setText("یک پیشنهاد را انتخاب کنید یا کد کالا را بنویسید.")
            return
        self.kala_code = code
        self.label = self.label_input.text().strip()
        self.accept()


class TextDialog(QDialog):
    """یک متن کوتاه یا چندخطی (برچسب، نام‌های دیگر)."""

    def __init__(self, title: str, hint: str, value: str = "", *, multiline: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.value = value
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(widgets.label(title, size=14, bold=True))
        root.addWidget(widgets.label(hint, name="Muted", wrap=True))
        if multiline:
            self.input = QPlainTextEdit(value)
            self.input.setMinimumHeight(140)
        else:
            self.input = QLineEdit(value)
            self.input.setMaxLength(60)
        root.addWidget(self.input)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(widgets.button("انصراف", on_click=self.reject))
        buttons.addWidget(widgets.button("ذخیره", icon_name="check", variant="primary",
                                         on_click=self._accept))
        root.addLayout(buttons)

    def _accept(self) -> None:
        widget = self.input
        text = widget.toPlainText() if isinstance(widget, QPlainTextEdit) else widget.text()
        self.value = text.strip()
        self.accept()
