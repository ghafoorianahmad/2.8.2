"""v2.11.0 صفحهٔ «سایت» — گوشی‌ها و لوازم جانبی سایت، فقط روی همین رایانه (بدون سرور فروشگاه).

* «گوشی‌ها»: فهرست با «نمایش/پنهان در سایت»، «افزودن گوشی جدید»، «ویرایش».
* «لوازم جانبی»: افزودن / ویرایش / پنهان؛ «خواندن از PDF…» کمکی است.
* v2.12.0 «ظاهر و چیدمان» (``app.ui.site_look``): ترتیب برندها و کالاها، «تازه‌ترین گوشی‌ها»،
  رنگ‌بندی آماده، لوگو، بنر، بخش‌های صفحهٔ اصلی، اطلاعات فروشگاه — بدون کد؛ و «پیش‌نمایش در
  مرورگر» (همان سایت با دادهٔ این رایانه، روی 127.0.0.1).
* «انتشار و پشتیبان»: «پیش‌نمایش» (دقیقاً چه چیزی در سایت عوض می‌شود)، «انتشار در سایت»
  (یک commit در مخزن GitHub سایت با توکنی که خود مالک وارد می‌کند)، «برگرداندن انتشار
  قبلی» (فقط تا ۴۸ ساعت)، توکن (رمزگذاری‌شده با ویندوز)، «آزمایش اتصال»، خواندن داده از سایت،
  پشتیبان‌گیری و بازگردانی.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import paths
from ...permissions import CATALOG_MANAGE
from ...persian import format_int, format_shamsi
from ...site import catalog as cat
from ...site import github as gh_mod
from ...site import preview as pv
from ...site import publish as pub
from ...site import token as tk
from ...site.store import SiteDataError, SiteStore
from .. import theme, widgets
from ..async_utils import run_async
from ..base_page import BasePage
from ..rtl import mark_ltr
from ..site_dialogs import AccessoryDialog, AccessoryPdfDialog, PhoneDialog
from ..site_look import LookTab

NL = chr(10)
PHONE_HEADERS = ("برند", "گوشی", "رنگ‌ها", "عکس", "در سایت")
ACCESSORY_HEADERS = ("نوع", "عنوان", "عکس", "در سایت")
#: v2.12.0: the site folder of «خواندن از پوشهٔ سایت…» = the code of the browser preview
PREVIEW_FOLDER_SETTING = "site_preview_folder"


# ---- pure helpers (tested without a window) ------------------------------------------
def photo_state(store: SiteStore, item: dict) -> str:
    refs = cat.image_refs(item)
    have = sum(1 for name in refs if store.has_photo(name))
    if not refs or not have:
        return "ندارد"
    return "کامل" if have == len(refs) else f"{format_int(have)} از {format_int(len(refs))}"


def matches(item: dict, text: str) -> bool:
    needle = " ".join(str(text or "").replace("ي", "ی").replace("ك", "ک").lower().split())
    if not needle:
        return True
    haystack = " ".join(str(item.get(k) or "") for k in ("name", "code", "brand", "brand_name"))
    haystack = haystack.replace("ي", "ی").replace("ك", "ک").lower()
    return all(part in haystack for part in needle.split())


def rollback_text(store: SiteStore, now: Optional[datetime] = None) -> str:
    found = store.last_rollback()
    if found is None:
        return "انتشاری در ۴۸ ساعت گذشته نیست که بشود برگرداند."
    deadline = store.rollback_deadline(found[1])
    left = (deadline - (now or datetime.now(timezone.utc))) if deadline else None
    hours = max(0, int(left.total_seconds() // 3600)) if left else 0
    return (f"آخرین انتشار ({format_shamsi(found[1].get('at'))}) تا {format_int(hours)} ساعت "
            "دیگر برگرداندنی است.")


def last_publish_text(store: SiteStore) -> str:
    last = store.published()
    if not last or not last.get("commit"):
        return "هنوز از این رایانه در سایت منتشر نشده است."
    return f"آخرین انتشار: {format_shamsi(last.get('at'))}"


class SitePage(BasePage):
    title = "سایت"
    subtitle = "گوشی‌ها و لوازم جانبی سایت — فقط روی همین رایانه نگه داشته می‌شود"
    help_text = ("گوشی یا لوازم جانبی اضافه، ویرایش یا پنهان کنید، «پیش‌نمایش» را ببینید و با "
                 "«انتشار در سایت» بفرستید.")
    reload_on_data_change = False
    refresh_on_server_events = False

    #: tests replace this with a fake GitHub transport (never the real repository)
    github_transport = None
    #: tests replace this (no browser is opened)
    open_url = staticmethod(lambda url: QDesktopServices.openUrl(QUrl(url)))

    def build_body(self) -> None:
        self.can_manage = self.context.can(CATALOG_MANAGE)
        self.store = SiteStore(self._root())
        self.banner = widgets.label("", wrap=True, bold=True)
        self.body.addWidget(self.banner)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._phones_tab(), "گوشی‌ها")
        self.tabs.addTab(self._accessories_tab(), "لوازم جانبی")
        self.look_tab = LookTab(self.store, can_manage=self.can_manage,
                                notify=self.notify_success, parent=self)
        self.look_tab.changed.connect(self.render)
        self.look_tab.add_action(widgets.button("پیش‌نمایش در مرورگر", icon_name="globe",
                                                on_click=self._preview_browser))
        look_publish = widgets.button("انتشار در سایت", icon_name="check", variant="primary",
                                      on_click=self._publish)
        look_publish.setEnabled(self.can_manage)
        self.look_tab.add_action(look_publish)
        self.tabs.addTab(self.look_tab, "ظاهر و چیدمان")
        self.tabs.addTab(self._publish_tab(), "انتشار و پشتیبان")
        self.body.addWidget(self.tabs, 1)

    def _root(self) -> Path:
        store_path = str(getattr(self.context.store, "path", "") or "")
        base = Path(store_path).parent if store_path and store_path != ":memory:" \
            else paths.data_dir()
        return base / "site"

    # ---- tabs ----------------------------------------------------------------------
    def _phones_tab(self) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)
        bar_holder = QWidget()
        bar = widgets.FlowLayout(bar_holder, spacing=8)
        self.phone_search = widgets.SearchBox("جستجوی گوشی…")
        self.phone_search.textChanged.connect(lambda _t: self.render())
        bar.addWidget(self.phone_search)
        self.add_phone_button = widgets.button("افزودن گوشی جدید", icon_name="plus",
                                               variant="primary", on_click=self._add_phone)
        self.edit_phone_button = widgets.button("ویرایش", icon_name="edit",
                                                on_click=self._edit_phone)
        self.toggle_phone_button = widgets.button("نمایش/پنهان در سایت", icon_name="eye",
                                                  on_click=lambda: self._toggle(self.phones_table,
                                                                                cat.KIND_PHONE))
        for b in (self.add_phone_button, self.edit_phone_button, self.toggle_phone_button):
            b.setEnabled(self.can_manage)
            bar.addWidget(b)
        box.addWidget(bar_holder)
        self.phones_table = widgets.DataTable(PHONE_HEADERS, selectable_rows=True, key="site_phones")
        self.phones_table.set_empty_state("هنوز گوشی‌ای نیست",
                                          "در «انتشار و پشتیبان»، «خواندن از سایت» را بزنید.", "file")
        self.phones_table.setMinimumHeight(320)
        self.phones_table.row_activated.connect(lambda _r: self._edit_phone())
        box.addWidget(self.phones_table, 1)
        self.phones_summary = widgets.label("", name="Muted")
        box.addWidget(self.phones_summary)
        return tab

    def _accessories_tab(self) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)
        bar_holder = QWidget()
        bar = widgets.FlowLayout(bar_holder, spacing=8)
        self.add_accessory_button = widgets.button("افزودن لوازم جانبی", icon_name="plus",
                                                   variant="primary", on_click=self._add_accessory)
        self.edit_accessory_button = widgets.button("ویرایش", icon_name="edit",
                                                    on_click=self._edit_accessory)
        self.toggle_accessory_button = widgets.button(
            "نمایش/پنهان در سایت", icon_name="eye",
            on_click=lambda: self._toggle(self.accessories_table, cat.KIND_ACCESSORY))
        self.pdf_button = widgets.button("خواندن از PDF…", icon_name="file",
                                         on_click=self._read_pdf,
                                         tooltip="کمکی: عنوان، مشخصات و عکس کالاها از PDF")
        for b in (self.add_accessory_button, self.edit_accessory_button,
                  self.toggle_accessory_button, self.pdf_button):
            b.setEnabled(self.can_manage)
            bar.addWidget(b)
        box.addWidget(bar_holder)
        self.accessories_table = widgets.DataTable(ACCESSORY_HEADERS, selectable_rows=True,
                                                   key="site_accessories")
        self.accessories_table.set_empty_state("هنوز لوازم جانبی‌ای نیست",
                                               "«افزودن لوازم جانبی» را بزنید.", "box")
        self.accessories_table.setMinimumHeight(320)
        self.accessories_table.row_activated.connect(lambda _r: self._edit_accessory())
        box.addWidget(self.accessories_table, 1)
        return tab

    def _publish_tab(self) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)
        box.addWidget(widgets.label("پیش‌نمایش — همین تغییرها با «انتشار» در سایت دیده می‌شود:",
                                    bold=True, wrap=True))
        self.preview_box = QPlainTextEdit()
        self.preview_box.setReadOnly(True)
        self.preview_box.setMinimumHeight(150)
        box.addWidget(self.preview_box)
        self.publish_state = widgets.label("", name="Muted", wrap=True)
        box.addWidget(self.publish_state)
        actions = QWidget()
        flow = widgets.FlowLayout(actions, spacing=8)
        self.preview_button = widgets.button("پیش‌نمایش", icon_name="eye", on_click=self.render)
        self.browser_button = widgets.button("پیش‌نمایش در مرورگر", icon_name="globe",
                                             on_click=self._preview_browser)
        self.publish_button = widgets.button("انتشار در سایت", icon_name="check",
                                             variant="primary", on_click=self._publish)
        self.rollback_button = widgets.button("برگرداندن انتشار قبلی", icon_name="refresh",
                                              on_click=self._rollback)
        for b in (self.publish_button, self.preview_button, self.browser_button,
                  self.rollback_button):
            flow.addWidget(b)
        box.addWidget(actions)

        token_panel = widgets.Panel()
        token_panel.body.addWidget(widgets.label("اتصال به GitHub سایت", bold=True))
        row = QHBoxLayout()
        row.addWidget(widgets.label("توکن:"))
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setPlaceholderText("github_pat_…")
        mark_ltr(self.token_input)
        row.addWidget(self.token_input, 1)
        token_panel.body.addLayout(row)
        repo_row = QHBoxLayout()
        repo_row.addWidget(widgets.label("مخزن:"))
        self.repo_input = QLineEdit(str(self.context.store.get_setting(
            tk.REPO_SETTING, gh_mod.DEFAULT_REPO) or gh_mod.DEFAULT_REPO))
        mark_ltr(self.repo_input)
        repo_row.addWidget(self.repo_input, 1)
        token_panel.body.addLayout(repo_row)
        self.token_state = widgets.label("", name="Muted", wrap=True)
        token_panel.body.addWidget(self.token_state)
        token_actions = QWidget()
        tflow = widgets.FlowLayout(token_actions, spacing=8)
        self.save_token_button = widgets.button("ذخیرهٔ توکن", icon_name="lock",
                                                on_click=self._save_token)
        self.test_button = widgets.button("آزمایش اتصال", icon_name="wifi",
                                          on_click=self._test_connection)
        self.forget_button = widgets.button("حذف توکن", icon_name="trash",
                                            on_click=self._forget_token)
        for b in (self.save_token_button, self.test_button, self.forget_button):
            tflow.addWidget(b)
        token_panel.body.addWidget(token_actions)
        box.addWidget(token_panel)

        data_panel = widgets.Panel()
        data_panel.body.addWidget(widgets.label("داده‌های سایت روی این رایانه", bold=True))
        data_actions = QWidget()
        dflow = widgets.FlowLayout(data_actions, spacing=8)
        self.seed_button = widgets.button("خواندن از سایت", icon_name="download",
                                          on_click=self._seed_github,
                                          tooltip="گوشی‌ها و عکس‌های فعلی سایت از GitHub")
        self.seed_folder_button = widgets.button("خواندن از پوشهٔ سایت…", icon_name="folder",
                                                 on_click=self._seed_folder)
        self.backup_button = widgets.button("پشتیبان‌گیری…", icon_name="save",
                                            on_click=self._backup)
        self.restore_button = widgets.button("بازگردانی از پشتیبان…", icon_name="archive",
                                             on_click=self._restore)
        for b in (self.seed_button, self.seed_folder_button, self.backup_button,
                  self.restore_button):
            dflow.addWidget(b)
        data_panel.body.addWidget(data_actions)
        data_panel.body.addWidget(widgets.label(
            "داده‌ها و عکس‌ها فقط روی همین رایانه است (پوشهٔ دادهٔ «مدیریت فروشگاه»)؛ "
            "پشتیبان را روی فلش یا رایانهٔ دیگری هم نگه دارید.", name="Muted", wrap=True))
        box.addWidget(data_panel)
        for b in (self.publish_button, self.rollback_button, self.save_token_button,
                  self.test_button, self.forget_button, self.seed_button,
                  self.seed_folder_button, self.restore_button):
            b.setEnabled(self.can_manage)
        box.addStretch(1)
        return tab

    # ---- data ------------------------------------------------------------------------
    def load(self) -> None:
        self.store.purge_history()
        self.look_tab.fill()
        self.render()

    def soft_refresh(self) -> None:
        self.render()

    def render(self) -> None:
        phones = self.store.items(cat.KIND_PHONE)
        accessories = self.store.items(cat.KIND_ACCESSORY)
        brands = {b["key"]: b["name"] for b in self.store.load()["brands"]}
        self._phones = [p for p in phones if matches(p, self.phone_search.text())]
        table = self.phones_table
        table.setRowCount(0)
        for item in self._phones:
            i = table.rowCount()
            table.insertRow(i)
            table.set_cell(i, 0, brands.get(item["brand"], item["brand"] or "—"))
            table.set_cell(i, 1, item["name"], bold=True)
            table.set_cell(i, 2, "، ".join(c["name"] for c in item["colors"]) or "—")
            table.set_cell(i, 3, photo_state(self.store, item))
            table.set_widget(i, 4, widgets.pill_cell(widgets.StatusPill(
                "پنهان" if item["hidden"] else "نمایش", "warning" if item["hidden"] else "success")))
        table._refresh_states()
        self._accessories = accessories
        table = self.accessories_table
        table.setRowCount(0)
        for item in accessories:
            i = table.rowCount()
            table.insertRow(i)
            table.set_cell(i, 0, cat.GROUPS.get(item["group"], "سایر"))
            table.set_cell(i, 1, item["name"], bold=True)
            table.set_cell(i, 2, photo_state(self.store, item))
            table.set_widget(i, 3, widgets.pill_cell(widgets.StatusPill(
                "پنهان" if item["hidden"] else "نمایش", "warning" if item["hidden"] else "success")))
        table._refresh_states()
        shown = sum(1 for p in phones if not p["hidden"])
        self.phones_summary.setText(f"{format_int(len(phones))} گوشی؛ "
                                    f"{format_int(shown)} در سایت نمایش داده می‌شود")
        self.look_tab.fill_lists()
        preview = self.store.preview()
        lines = list(preview["lines"])
        if preview["problems"] or preview["look_problems"]:
            lines = ["⚠ " + p for p in preview["problems"] + preview["look_problems"]] + lines
        self.preview_box.setPlainText(NL.join(lines))
        self.publish_state.setText(last_publish_text(self.store) + NL + rollback_text(self.store))
        self.rollback_button.setEnabled(self.can_manage and self.store.last_rollback() is not None)
        self.token_state.setText("توکن ذخیره شده است (رمزگذاری‌شده با ویندوز؛ نشان داده نمی‌شود)."
                                 if tk.has_token(self.context.store) else
                                 "هنوز توکنی ذخیره نشده است.")
        if self.store.is_empty():
            self.banner.setText("هنوز داده‌ای نیست؛ در «انتشار و پشتیبان» «خواندن از سایت» "
                                "(یا «خواندن از پوشهٔ سایت…») را بزنید.")
            self.banner.setStyleSheet(f"color: {theme.WARNING_TEXT};")
        else:
            changes = "تغییر منتشرنشده دارد." if preview["has_changes"] else "با سایت یکی است."
            self.banner.setText(f"{format_int(len(phones))} گوشی و {format_int(len(accessories))} "
                                f"لوازم جانبی — {changes}")
            self.banner.setStyleSheet(
                f"color: {theme.WARNING_TEXT if preview['has_changes'] else theme.SUCCESS_DARK};")

    # ---- helpers -----------------------------------------------------------------------
    def _selected(self, table, rows: list[dict]) -> Optional[dict]:
        picked = sorted({index.row() for index in table.selectionModel().selectedRows()})
        if len(picked) != 1 or not 0 <= picked[0] < len(rows):
            self.notify_warning("یک ردیف را انتخاب کنید.")
            return None
        return rows[picked[0]]

    def _publisher(self) -> gh_mod.GitHubPublisher:
        token = tk.load(self.context.store)
        if not token:
            raise gh_mod.GitHubError("اول توکن GitHub را وارد و «ذخیرهٔ توکن» را بزنید.")
        return gh_mod.GitHubPublisher(token, self.repo_input.text().strip() or gh_mod.DEFAULT_REPO,
                                      transport=self.github_transport)

    def _background(self, work: Callable, done: Callable[[dict], None], busy: str) -> None:
        """GitHub work off the GUI thread; Persian errors as a result, never raised."""
        def task():
            try:
                return {"ok": True, "result": work()}
            except (gh_mod.GitHubError, SiteDataError, tk.TokenError) as exc:
                return {"ok": False, "error": str(exc)}

        def finished(outcome: dict) -> None:
            self.render()
            if outcome.get("ok"):
                done(outcome["result"])
            else:
                widgets.error(self, "سایت", outcome.get("error") or "انجام نشد.")

        # not self.run(): a GitHub answer must not mark the shop server as reachable
        self.set_busy(True, busy)
        run_async(task, on_success=finished, on_error=lambda message, _kind: widgets.error(
            self, "سایت", message), on_done=lambda: self.set_busy(False))

    # ---- phones / accessories ----------------------------------------------------------
    def _add_phone(self) -> None:
        if PhoneDialog(self.store, parent=self).exec() == QDialog.DialogCode.Accepted:
            self.notify_success("گوشی اضافه شد؛ با «انتشار در سایت» در سایت دیده می‌شود.")
        self.render()

    def _edit_phone(self) -> None:
        item = self._selected(self.phones_table, self._phones)
        if item and self.can_manage and PhoneDialog(self.store, item, parent=self).exec():
            self.notify_success("ذخیره شد.")
        self.render()

    def _add_accessory(self) -> None:
        if AccessoryDialog(self.store, parent=self).exec() == QDialog.DialogCode.Accepted:
            self.notify_success("لوازم جانبی اضافه شد.")
        self.render()

    def _edit_accessory(self) -> None:
        item = self._selected(self.accessories_table, self._accessories)
        if item and self.can_manage and AccessoryDialog(self.store, item, parent=self).exec():
            self.notify_success("ذخیره شد.")
        self.render()

    def _toggle(self, table, kind: str) -> None:
        rows = self._phones if kind == cat.KIND_PHONE else self._accessories
        item = self._selected(table, rows)
        if item is None:
            return
        self.store.set_hidden(item["code"], not item["hidden"])
        self.notify_success(f"«{item['name']}» " + ("در سایت نمایش داده می‌شود." if item["hidden"]
                                                     else "در سایت پنهان می‌شود."))
        self.render()

    def _read_pdf(self) -> None:
        path, _f = QFileDialog.getOpenFileName(self, "انتخاب PDF لوازم جانبی", "", "PDF (*.pdf)")
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError:
            self.notify_error("این فایل خوانده نشد.")
            return
        dialog = AccessoryPdfDialog(self.store, data, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.notify_success(f"{format_int(dialog.added)} لوازم جانبی اضافه شد.")
        self.render()

    # ---- publish -----------------------------------------------------------------------
    def _publish(self) -> None:
        if not self.look_tab.save_pending():
            return
        preview = self.store.preview()
        if preview["problems"]:
            widgets.error(self, "انتشار", "، ".join(preview["problems"]))
            return
        never = not (self.store.published() or {}).get("commit")
        if not preview["has_changes"] and not never:
            self.notify_warning("تغییری برای انتشار نیست.")
            return
        message = NL.join(preview["lines"][:12])
        if not widgets.confirm(self, "انتشار در سایت", "این تغییرها در سایت منتشر شود؟" + NL + NL
                               + message, confirm_text="انتشار"):
            return
        from ... import paths as _paths

        def work():
            with self._publisher() as gh:
                return pub.publish(self.store, gh, generator=f"ShopAdmin {_paths.APP_VERSION}")

        self._background(work, lambda out: widgets.success(
            self, "انتشار در سایت", out["note"]), "در حال انتشار در سایت…")

    def _rollback(self) -> None:
        if not widgets.confirm(self, "برگرداندن انتشار قبلی",
                               "سایت به حالت پیش از آخرین انتشار برگردد؟",
                               confirm_text="برگرداندن", kind="warning"):
            return

        def work():
            with self._publisher() as gh:
                return pub.rollback(self.store, gh)

        self._background(work, lambda out: widgets.success(
            self, "برگرداندن انتشار", out["note"]), "در حال برگرداندن…")

    def _save_token(self) -> None:
        try:
            tk.save(self.context.store, self.token_input.text())
        except tk.TokenError as exc:
            widgets.error(self, "توکن", str(exc))
            return
        self.context.store.set_setting(tk.REPO_SETTING, self.repo_input.text().strip()
                                       or gh_mod.DEFAULT_REPO)
        self.token_input.clear()
        self.notify_success("توکن ذخیره شد.")
        self.render()

    def _forget_token(self) -> None:
        tk.forget(self.context.store)
        self.notify_success("توکن حذف شد.")
        self.render()

    def _test_connection(self) -> None:
        def work():
            with self._publisher() as gh:
                return gh.test_connection()

        self._background(work, lambda out: widgets.success(
            self, "آزمایش اتصال", f"اتصال درست است؛ مخزن {out['repo']} و اجازهٔ نوشتن دارد."),
            "در حال آزمایش اتصال…")

    # ---- data on this computer ---------------------------------------------------------
    def _seed_github(self) -> None:
        def work():
            with self._publisher() as gh:
                return pub.seed_from_github(self.store, gh)

        self._background(work, self._seeded, "در حال خواندن از سایت (چند دقیقه)…")

    def _seed_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "پوشهٔ اصلی سایت (همان که index.html دارد)")
        if not folder:
            return
        try:
            out = self.store.seed_from_folder(folder)
        except SiteDataError as exc:
            widgets.error(self, "خواندن از پوشهٔ سایت", str(exc))
            return
        self.context.store.set_setting(PREVIEW_FOLDER_SETTING, str(folder))
        self._seeded(out)
        self.render()

    # ---- v2.12.0 browser preview --------------------------------------------------------
    def _preview_folder(self) -> Optional[Path]:
        folder = str(self.context.store.get_setting(PREVIEW_FOLDER_SETTING, "") or "")
        if folder:
            try:
                return pv.base_from_folder(folder)
            except SiteDataError:
                return None
        return None

    def _preview_browser(self) -> None:
        """The real site with this computer's data, in the computer's browser."""
        if not self.look_tab.save_pending():
            return
        from ... import paths as _paths

        generator = f"ShopAdmin {_paths.APP_VERSION}"
        base = self._preview_folder()
        if base is not None:
            try:
                self._open_preview(pv.build(self.store, base, self.store.root / "preview",
                                            generator=generator))
            except (OSError, SiteDataError) as exc:
                widgets.error(self, "پیش‌نمایش", str(exc) if isinstance(exc, SiteDataError)
                              else "پوشهٔ پیش‌نمایش ساخته نشد.")
            return
        if not tk.has_token(self.context.store):
            widgets.error(self, "پیش‌نمایش در مرورگر",
                          "برای پیش‌نمایش کد خود سایت لازم است: یک بار در «انتشار و پشتیبان» "
                          "«خواندن از پوشهٔ سایت…» را بزنید یا توکن GitHub را ذخیره کنید.")
            return

        def work():
            with self._publisher() as gh:
                base_dir = pv.base_from_github(gh, self.store.root / "site_base")
            return pv.build(self.store, base_dir, self.store.root / "preview", generator=generator)

        self._background(work, self._open_preview, "در حال آماده کردن پیش‌نمایش…")

    def _open_preview(self, out: dict) -> None:
        url = pv.PreviewServer.url(out["dir"])
        self.last_preview_url = url
        self.open_url(url)
        if out["look_supported"]:
            self.notify_success("پیش‌نمایش در مرورگر باز شد (فقط روی همین رایانه).")
        else:
            widgets.info(self, "پیش‌نمایش در مرورگر",
                         "پیش‌نمایش باز شد، ولی این نسخهٔ کد سایت «ظاهر و چیدمان» را نمی‌شناسد؛ "
                         "گوشی‌ها و لوازم جانبی درست دیده می‌شوند ولی رنگ، بنر و چیدمان نه. "
                         "نسخهٔ تازهٔ سایت باید در GitHub (یا پوشهٔ سایت) باشد.", kind="warning")

    def _seeded(self, out: dict) -> None:
        text = (f"{format_int(out['models'])} کالا خوانده شد ({format_int(out['added'])} تازه)، "
                f"{format_int(out['photos'])} عکس.")
        if out.get("missing_photos"):
            text += f" {format_int(out['missing_photos'])} عکس پیدا نشد."
        self.look_tab.fill()
        widgets.success(self, "خواندن از سایت", text)

    def _backup(self) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d")
        path, _f = QFileDialog.getSaveFileName(self, "پشتیبان بخش سایت",
                                               f"site-backup-{stamp}.zip", "zip (*.zip)")
        if not path:
            return
        try:
            count = self.store.backup(path)
        except OSError:
            widgets.error(self, "پشتیبان", "فایل در این پوشه ذخیره نشد؛ پوشهٔ دیگری انتخاب کنید.")
            return
        widgets.success(self, "پشتیبان", f"پشتیبان ذخیره شد ({format_int(count)} عکس).")

    def _restore(self) -> None:
        path, _f = QFileDialog.getOpenFileName(self, "بازگردانی بخش سایت", "", "zip (*.zip)")
        if not path:
            return
        if not widgets.confirm(self, "بازگردانی", "داده‌های فعلی سایت با این پشتیبان جایگزین شود؟ "
                               "(یک رونوشت از داده‌های فعلی هم نگه داشته می‌شود)",
                               confirm_text="بازگردانی", kind="warning"):
            return
        try:
            out = self.store.restore(path)
        except SiteDataError as exc:
            widgets.error(self, "بازگردانی", str(exc))
            return
        self.look_tab.fill()
        widgets.success(self, "بازگردانی", f"{format_int(out['items'])} کالا و "
                                          f"{format_int(out['photos'])} عکس بازگردانده شد.")
        self.render()
