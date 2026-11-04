"""v2.18.1 «پاسخ‌گوی خودکار»: کلید روشن و خاموش، پرسش و پاسخ‌ها، و پیشنهادهایی که از پاسخ همکاران
به مشتری ساخته شده و تا تأیید مدیر به کار نمی‌رود.

ویرایش پرسش‌های آماده جدا از فایل نگه داشته می‌شود و نسخهٔ تازه آن را از بین نمی‌برد.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...permissions import FAQ_EDIT
from ...persian import format_datetime_shamsi, to_persian_digits
from .. import widgets
from ..base_page import BasePage
from ..rtl import RIGHT

ITEM_HEADERS = ("دسته", "نمونهٔ پرسش", "پاسخ", "همکار", "وضعیت")
SUGGESTION_HEADERS = ("زمان", "پرسش مشتری", "پاسخ همکار", "همکار")
ANSWERED_HEADERS = ("زمان", "متن مشتری", "پرسش", "امتیاز")


def item_state(item: dict) -> str:
    state = "روشن" if item.get("enabled", True) else "خاموش"
    if item.get("source") == "custom":
        return f"{state} (افزوده)"
    return f"{state} (ویرایش‌شده)" if item.get("edited") else state


class FaqItemDialog(widgets.ResponsiveDialog):
    """A question-and-answer: new, edited, or a colleague's reply being approved."""

    def __init__(self, item: dict, placeholders, parent: QWidget | None = None,
                 *, title: str = "پرسش و پاسخ") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(640)
        self.placeholders = list(placeholders)
        column = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(RIGHT | Qt.AlignmentFlag.AlignVCenter)
        self.category = QLineEdit(str(item.get("category") or ""))
        form.addRow(widgets.label("دسته:"), self.category)
        self.questions = QPlainTextEdit("\n".join(item.get("questions") or ()))
        self.questions.setMinimumHeight(130)
        form.addRow(widgets.label("پرسش‌ها (هر خط یکی):"), self.questions)
        self.answer = QPlainTextEdit(str(item.get("answer") or ""))
        self.answer.setMinimumHeight(120)
        form.addRow(widgets.label("پاسخ:"), self.answer)
        column.addLayout(form)
        names = "، ".join("{" + name + "}" for name in self.placeholders)
        column.addWidget(widgets.label(
            f"جای‌خالی‌هایی که از اطلاعات فروشگاه پر می‌شود: {names}. قیمت را در پاسخ ننویسید.",
            name="Muted", wrap=True))
        self.needs_staff = QCheckBox("همکار هم باید پاسخ بدهد (به مشتری گفته می‌شود و در «درخواست "
                                     "کالا» می‌آید)")
        self.needs_staff.setChecked(bool(item.get("needs_staff")))
        column.addWidget(self.needs_staff)
        self.enabled = QCheckBox("روشن: ربات از این پاسخ استفاده کند")
        self.enabled.setChecked(bool(item.get("enabled", True)))
        column.addWidget(self.enabled)
        self.problem = widgets.label("", wrap=True)
        self.problem.setVisible(False)
        column.addWidget(self.problem)
        column.addLayout(widgets.footer(
            widgets.button("ذخیره", variant="primary", on_click=self._save),
            close=widgets.button("انصراف", on_click=self.reject)))

    def values(self) -> dict:
        return {"category": self.category.text().strip(),
                "questions": [q.strip() for q in self.questions.toPlainText().splitlines()
                              if q.strip()],
                "answer": self.answer.toPlainText().strip(),
                "needs_staff": self.needs_staff.isChecked(), "enabled": self.enabled.isChecked()}

    def _save(self) -> None:
        values = self.values()
        problem = ("دست‌کم یک پرسش بنویسید." if not values["questions"] else
                   "متن پاسخ را بنویسید." if not values["answer"] else "")
        self.problem.setText(problem)
        self.problem.setVisible(bool(problem))
        if not problem:
            self.accept()


class FaqPage(BasePage):
    title = "پاسخ‌گوی خودکار"
    subtitle = "پرسش و پاسخ‌های ربات و پیشنهادهای تازه"
    help_text = ("ربات فقط وقتی پاسخ می‌دهد که پرسش را مطمئن بشناسد. جای‌خالی‌ها از اطلاعات فروشگاه پر "
                 "می‌شود و پاسخ‌هایی که به همکار نیاز دارد می‌گوید «یکی از همکاران پاسخ می‌دهد».")
    reload_on_data_change = False
    refresh_on_server_events = False

    def build_body(self) -> None:
        self.can_edit = self.context.can(FAQ_EDIT)
        self.items: list[dict] = []
        self.pending: list[dict] = []
        self.placeholders: list[str] = []

        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(16)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(holder)
        self.body.addWidget(scroll, 1)

        switch_panel = widgets.Panel("کلید")
        self.switch = QCheckBox("ربات به پرسش‌های پرتکرار خودش پاسخ بدهد")
        self.switch.setEnabled(self.can_edit)
        self.switch.clicked.connect(self._switched)
        switch_panel.body.addWidget(self.switch)
        self.counts = widgets.label("", name="Muted", wrap=True)
        switch_panel.body.addWidget(self.counts)
        column.addWidget(switch_panel)

        suggest_panel = widgets.Panel("پیشنهادهای تازه از پاسخ همکاران")
        suggest_panel.body.addWidget(widgets.label(
            "وقتی همکاری به پرسش مشتری پاسخ می‌دهد این‌جا پیشنهاد می‌شود. تا تأیید نکنید ربات از آن "
            "استفاده نمی‌کند. پاسخی که عدد بلند یا قیمت دارد پیشنهاد نمی‌شود.", name="Muted", wrap=True))
        self.suggest_table = widgets.DataTable(SUGGESTION_HEADERS, selectable_rows=True,
                                               fit_width=True, stretch_column=2)
        self.suggest_table.setMinimumHeight(200)
        self.suggest_table.set_empty_state("پیشنهادی نیست", "همهٔ پیشنهادها بررسی شده‌اند.", "check")
        self.suggest_table.row_activated.connect(lambda _row: self._approve())
        suggest_panel.body.addWidget(self.suggest_table)
        row = QHBoxLayout()
        self.approve_button = widgets.button("ویرایش و تأیید", variant="primary",
                                             on_click=self._approve)
        self.reject_button = widgets.button("رد پیشنهاد", on_click=self._reject)
        row.addWidget(self.approve_button)
        row.addWidget(self.reject_button)
        row.addStretch(1)
        suggest_panel.body.addLayout(row)
        column.addWidget(suggest_panel)

        items_panel = widgets.Panel("پرسش و پاسخ‌ها")
        self.search = widgets.SearchBox("جستجو در پرسش و پاسخ‌ها…")
        self.search.textChanged.connect(self._show_items)
        items_panel.body.addWidget(self.search)
        self.items_table = widgets.DataTable(ITEM_HEADERS, selectable_rows=True,
                                             fit_width=True, stretch_column=2)
        self.items_table.setMinimumHeight(360)
        self.items_table.set_empty_state("چیزی پیدا نشد")
        self.items_table.row_activated.connect(lambda _row: self._edit())
        items_panel.body.addWidget(self.items_table)
        row = QHBoxLayout()
        self.add_button = widgets.button("افزودن پرسش و پاسخ", icon_name="plus", on_click=self._add)
        self.edit_button = widgets.button("ویرایش", on_click=self._edit)
        self.toggle_button = widgets.button("روشن / خاموش", on_click=self._toggle)
        self.remove_button = widgets.button("حذف یا برگرداندن متن اصلی", on_click=self._remove)
        for button in (self.add_button, self.edit_button, self.toggle_button, self.remove_button):
            row.addWidget(button)
        row.addStretch(1)
        items_panel.body.addLayout(row)
        column.addWidget(items_panel)

        answered_panel = widgets.Panel("پاسخ‌های داده‌شده (تازه‌ترین‌ها)")
        self.answered_table = widgets.DataTable(ANSWERED_HEADERS, fit_width=True, stretch_column=1)
        self.answered_table.setMinimumHeight(220)
        self.answered_table.set_empty_state("هنوز پاسخی داده نشده")
        answered_panel.body.addWidget(self.answered_table)
        column.addWidget(answered_panel)
        column.addStretch(1)

        for button in (self.approve_button, self.reject_button, self.add_button, self.edit_button,
                       self.toggle_button, self.remove_button):
            button.setVisible(self.can_edit)

    def load(self) -> None:
        self.run(self.context.api.faq_page, on_success=self._loaded, on_error=self.default_error)

    def _loaded(self, data: object) -> None:
        data = data if isinstance(data, dict) else {}
        self.items = [i for i in data.get("items") or () if isinstance(i, dict)]
        self.pending = [i for i in data.get("suggestions") or () if isinstance(i, dict)]
        self.placeholders = [str(p) for p in data.get("placeholders") or ()]
        self.switch.setChecked(bool(data.get("enabled")))
        self.counts.setText(
            f"{to_persian_digits(sum(1 for i in self.items if i.get('enabled', True)))} پرسش و پاسخ "
            f"روشن از {to_persian_digits(len(self.items))}؛ "
            f"{to_persian_digits(len(self.pending))} پیشنهاد در انتظار تأیید.")
        self.suggest_table.fill([[format_datetime_shamsi(s.get("created_at")),
                                  str(s.get("question") or ""), str(s.get("answer") or ""),
                                  str(s.get("created_by") or "")] for s in self.pending])
        self.answered_table.fill([[format_datetime_shamsi(r.get("created_at")),
                                   str(r.get("query") or ""), str(r.get("faq_id") or ""),
                                   to_persian_digits(r.get("score") or 0)]
                                  for r in data.get("report") or () if isinstance(r, dict)])
        self._show_items()

    def _visible_items(self) -> list[dict]:
        needle = " ".join(self.search.text().split())
        if not needle:
            return self.items
        return [i for i in self.items if needle in str(i.get("category") or "")
                or needle in str(i.get("answer") or "")
                or any(needle in str(q) for q in i.get("questions") or ())]

    def _show_items(self, *_args) -> None:
        self.items_table.fill([[str(i.get("category") or ""),
                                str((i.get("questions") or [""])[0]), str(i.get("answer") or ""),
                                "بله" if i.get("needs_staff") else "—", item_state(i)]
                               for i in self._visible_items()])

    def _selected_item(self) -> dict | None:
        visible = self._visible_items()
        row = self.items_table.currentRow()
        if 0 <= row < len(visible):
            return visible[row]
        self.toasts.show_warning("اول یک ردیف را انتخاب کنید.")
        return None

    def _selected_suggestion(self) -> dict | None:
        row = self.suggest_table.currentRow()
        if 0 <= row < len(self.pending):
            return self.pending[row]
        self.toasts.show_warning("اول یک پیشنهاد را انتخاب کنید.")
        return None

    def _call(self, fn, done_text: str) -> None:
        def done(_answer: object) -> None:
            self.toasts.show_success(done_text)
            self.load()

        self.run(fn, on_success=done, on_error=self.default_error)

    def _switched(self, on: bool) -> None:
        self._call(lambda: self.context.api.set_faq(bool(on)),
                   "پاسخ‌گوی خودکار روشن شد." if on else "پاسخ‌گوی خودکار خاموش شد.")

    def _add(self) -> None:
        dialog = FaqItemDialog({"enabled": True}, self.placeholders, self,
                               title="افزودن پرسش و پاسخ")
        if dialog.exec() == dialog.DialogCode.Accepted:
            values = dialog.values()
            self._call(lambda: self.context.api.faq_save_item(None, values), "افزوده شد.")

    def _edit(self) -> None:
        item = self._selected_item()
        if item is None or not self.can_edit:
            return
        dialog = FaqItemDialog(item, self.placeholders, self, title="ویرایش پرسش و پاسخ")
        if dialog.exec() == dialog.DialogCode.Accepted:
            values = dialog.values()
            self._call(lambda: self.context.api.faq_save_item(item["id"], values), "ذخیره شد.")

    def _toggle(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        values = {key: item.get(key) for key in ("category", "questions", "answer", "needs_staff")}
        values["enabled"] = not item.get("enabled", True)
        self._call(lambda: self.context.api.faq_save_item(item["id"], values),
                   "روشن شد." if values["enabled"] else "خاموش شد.")

    def _remove(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        builtin = item.get("source") == "builtin"
        if builtin and not item.get("edited"):
            self.toasts.show_warning("این متن همان متن اصلی است؛ برای کنار گذاشتن، خاموشش کنید.")
            return
        question = ("متن اصلی این پرسش و پاسخ برگردد؟" if builtin
                    else "این پرسش و پاسخ حذف شود؟")
        if widgets.confirm(self, "پاسخ‌گوی خودکار", question, confirm_text="بله"):
            self._call(lambda: self.context.api.faq_remove_item(item["id"]), "انجام شد.")

    def _approve(self) -> None:
        suggestion = self._selected_suggestion()
        if suggestion is None or not self.can_edit:
            return
        dialog = FaqItemDialog({"category": "آموخته از همکاران",
                                "questions": [suggestion.get("question") or ""],
                                "answer": suggestion.get("answer") or "", "enabled": True},
                               self.placeholders, self, title="تأیید پیشنهاد")
        if dialog.exec() == dialog.DialogCode.Accepted:
            values = dialog.values()
            self._call(lambda: self.context.api.faq_approve(int(suggestion["id"]), values),
                       "تأیید شد؛ ربات از این پس از آن استفاده می‌کند.")

    def _reject(self) -> None:
        suggestion = self._selected_suggestion()
        if suggestion is not None:
            self._call(lambda: self.context.api.faq_reject(int(suggestion["id"])), "رد شد.")
