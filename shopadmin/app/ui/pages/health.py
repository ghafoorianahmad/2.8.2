"""v2.14.0 صفحهٔ «سلامت سیستم» — سرور خودش را مرتب بررسی می‌کند.

* بالا: هر بخش اکنون (SQL، ربات بله، اتصال بله، کارگر تلگرام، پشتیبان، فضای دیسک) و راه رفعش؛
* پایین: آنچه پیدا شد، آنچه خودکار برطرف شد (اتصال دوباره، خواندن دوبارهٔ لیست، راه‌اندازی دوبارهٔ
  کارگر) و آنچه به شما نیاز دارد. کار پرخطر (ثبت در حسابداری، پاک کردن داده، تغییر قیمت) هرگز
  خودکار نیست؛ فقط خبر داده می‌شود.
"""
from __future__ import annotations

from ...permissions import HEALTH_VIEW
from ...persian import format_int, format_shamsi
from .. import widgets
from ..base_page import BasePage

CHECK_HEADERS = ("بخش", "وضعیت", "اگر مشکل دارد")
JOURNAL_HEADERS = ("زمان", "بخش", "چه شد", "کار شما")
KIND_FA = {"found": ("پیدا شد", "info"), "fixed": ("خودکار برطرف شد", "success"),
           "needs_you": ("نیاز به شما", "warning")}


def state_of(check: dict) -> tuple[str, str]:
    if check.get("ok") is None:
        return "بررسی نمی‌شود", ""
    if check.get("down"):
        return "مشکل دارد", "danger"
    return ("سالم", "success") if check.get("ok") else ("در حال بررسی دوباره", "warning")


class HealthPage(BasePage):
    title = "سلامت سیستم"
    subtitle = "آنچه سرور خودش پیدا و برطرف کرد، و آنچه به شما نیاز دارد"
    help_text = ("سرور هر چند دقیقه خودش را بررسی می‌کند و مشکلات معمول را خودکار برطرف می‌کند؛ "
                 "کار پرخطر هیچ‌وقت خودکار نیست.")
    auto_refreshable = True

    def build_body(self) -> None:
        panel = widgets.Panel("وضعیت اکنون")
        self.checked = widgets.label("", name="Muted")
        panel.body.addWidget(self.checked)
        self.checks_table = widgets.DataTable(CHECK_HEADERS, key="health_checks", stretch_column=2,
                                              fit_width=True)
        self.checks_table.set_empty_state("هنوز بررسی‌ای انجام نشده",
                                          "چند دقیقه پس از روشن شدن سرور اولین بررسی انجام می‌شود.",
                                          "server")
        self.checks_table.setMinimumHeight(220)
        panel.body.addWidget(self.checks_table)
        self.body.addWidget(panel)
        journal = widgets.Panel("گزارش")
        self.counts = widgets.label("", bold=True, wrap=True)
        journal.body.addWidget(self.counts)
        self.journal_table = widgets.DataTable(JOURNAL_HEADERS, key="health_journal",
                                               selectable_rows=True, stretch_column=2)
        self.journal_table.set_empty_state("چیزی ثبت نشده", "همه‌چیز آرام است.", "check")
        self.journal_table.setMinimumHeight(260)
        journal.body.addWidget(self.journal_table, 1)
        self.body.addWidget(journal, 1)

    def load(self) -> None:
        if not self.context.can(HEALTH_VIEW):
            return
        self.run(self.context.api.server_health, on_success=self._loaded,
                 on_error=lambda m, _k: self.show_table_error(m))

    def _loaded(self, data: dict) -> None:
        data = data or {}
        self.checked.setText("آخرین بررسی: " + (format_shamsi(data.get("checked_at"))
                                                if data.get("checked_at") else "هنوز نه"))
        table = self.checks_table
        table.setRowCount(0)
        for check in data.get("checks") or []:
            i = table.rowCount()
            table.insertRow(i)
            table.set_cell(i, 0, check.get("label") or check.get("check") or "", bold=True)
            text, status = state_of(check)
            table.set_widget(i, 1, widgets.pill_cell(widgets.StatusPill(text, status)))
            table.set_cell(i, 2, check.get("fix") if check.get("down") else "—",
                           tooltip=check.get("fix") or "")
            table.set_row_key(i, check.get("check"))
        table._refresh_states()
        entries = list(data.get("journal") or [])
        table = self.journal_table
        table.setRowCount(0)
        for entry in entries:
            i = table.rowCount()
            table.insertRow(i)
            table.set_cell(i, 0, format_shamsi(entry.get("at")))
            table.set_cell(i, 1, entry.get("label") or "")
            kind, status = KIND_FA.get(entry.get("kind"), (entry.get("kind") or "", ""))
            table.set_cell(i, 2, f"{kind}: {entry.get('text') or ''}",
                           tooltip=entry.get("text") or "")
            table.set_cell(i, 3, entry.get("fix") or "—", tooltip=entry.get("fix") or "")
        table._refresh_states()
        totals = {k: sum(1 for e in entries if e.get("kind") == k) for k in KIND_FA}
        self.counts.setText(f"خودکار برطرف شد: {format_int(totals['fixed'])} — نیاز به شما: "
                            f"{format_int(totals['needs_you'])} — پیدا شد: {format_int(totals['found'])}")
