"""v2.11.0 صفحهٔ «سایت» — گوشی‌ها و لوازم جانبی سایت، فقط روی همین رایانه (بدون سرور فروشگاه).

* v2.14.0 «کالاها»: یک درخت — «گوشی‌ها» ← برند ← مدل، «لوازم جانبی» ← دسته ← کالا. روی هر
  شاخه: «افزودن از PDF» (کالاها به همان دسته می‌روند؛ دسته حدس زده نمی‌شود)، «افزودن دستی»،
  «زیرشاخهٔ تازه»، «تغییر نام». کنار درخت فهرست کالاهای همان شاخه: یک کلیک = انتخاب، دوبار
  کلیک یا «ویرایش» = ویرایش، قرص «نمایش/پنهان» با کلیک عوض می‌شود، «حذف» (با تأیید؛ تا ۴۸
  ساعت «برگرداندن حذف‌شده‌ها»).
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
    QInputDialog,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
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
from ..site_dialogs import AccessoryDialog, PhoneDialog
from ..site_import import PdfImportDialog
from ..site_look import LookTab

NL = chr(10)
PHONE_HEADERS = ("برند", "گوشی", "رنگ‌ها", "عکس", "در سایت")
ACCESSORY_HEADERS = ("دسته", "عنوان", "برند", "عکس", "در سایت")
#: v2.14.0 tree nodes: (kind, key) in the item's UserRole
NODE_PHONES, NODE_BRAND, NODE_PHONE = "phones", "brand", "phone"
NODE_ACCESSORIES, NODE_GROUP, NODE_ACCESSORY = "accessories", "group", "accessory"
#: brands the site has a page for (a phone of another brand is kept here only)
SITE_BRAND_PAGES = ("apple", "samsung", "xiaomi")
#: v2.12.0: the site folder of «خواندن از پوشهٔ سایت…» = the code of the browser preview
PREVIEW_FOLDER_SETTING = "site_preview_folder"


# ---- pure helpers (tested without a window) ------------------------------------------
def photo_state(store: SiteStore, item: dict) -> str:
    refs = cat.image_refs(item)
    have = sum(1 for name in refs if store.has_photo(name))
    if not refs or not have:
        return "ندارد"
    return "کامل" if have == len(refs) else f"{format_int(have)} از {format_int(len(refs))}"


def count_text(counts: dict, noun: str) -> str:
    """v2.14.0: «۶۶ گوشی (۶۳ در سایت، ۳ پنهان)»."""
    text = f"{format_int(counts['total'])} {noun} ({format_int(counts['shown'])} در سایت"
    if counts["hidden"]:
        text += f"، {format_int(counts['hidden'])} پنهان"
    return text + ")"


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
        self.tabs.addTab(self._items_tab(), "کالاها")
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
    def _items_tab(self) -> QWidget:
        """v2.14.0: the tree of branches + the items of the chosen branch."""
        tab = QWidget()
        box = QVBoxLayout(tab)
        bar_holder = QWidget()
        bar = widgets.FlowLayout(bar_holder, spacing=8)
        self.add_button = widgets.button("افزودن دستی", icon_name="plus", variant="primary",
                                         on_click=self._add_manual)
        self.pdf_button = widgets.button("افزودن از PDF…", icon_name="file",
                                         on_click=self._read_pdf,
                                         tooltip="کالاهای یک یا چند PDF به همین دستهٔ لوازم جانبی")
        self.branch_button = widgets.button("زیرشاخهٔ تازه", icon_name="plus",
                                            on_click=self._new_branch,
                                            tooltip="برند تازه زیر «گوشی‌ها» یا دستهٔ تازه زیر "
                                                    "«لوازم جانبی»")
        self.rename_button = widgets.button("تغییر نام", icon_name="edit",
                                            on_click=self._rename_branch)
        self.undelete_button = widgets.button("برگرداندن حذف‌شده‌ها…", icon_name="refresh",
                                              on_click=self._undelete)
        # the old names (tests, audits)
        self.add_phone_button = self.add_accessory_button = self.add_button
        for b in (self.add_button, self.pdf_button, self.branch_button, self.rename_button,
                  self.undelete_button):
            b.setEnabled(self.can_manage)
            bar.addWidget(b)
        box.addWidget(bar_holder)
        self.branch_hint = widgets.label("", name="Muted", wrap=True)
        box.addWidget(self.branch_hint)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.tree.setMinimumWidth(230)
        self.tree.currentItemChanged.connect(lambda _new, _old: self._node_changed())
        splitter.addWidget(self.tree)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._phones_panel())
        self.stack.addWidget(self._accessories_panel())
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 760])
        box.addWidget(splitter, 1)
        return tab

    def _item_bar(self, kind: str) -> tuple[QWidget, list]:
        holder = QWidget()
        bar = widgets.FlowLayout(holder, spacing=8)
        edit = widgets.button("ویرایش", icon_name="edit",
                              on_click=self._edit_phone if kind == cat.KIND_PHONE
                              else self._edit_accessory)
        delete = widgets.button("حذف", icon_name="trash", on_click=lambda: self._delete(kind))
        buttons = [edit, delete]
        for b in buttons:
            b.setEnabled(self.can_manage)
            bar.addWidget(b)
        return holder, buttons

    def _phones_panel(self) -> QWidget:
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(10, 0, 10, 0)   # never flush against the tree
        holder, (self.edit_phone_button, self.delete_phone_button) = self._item_bar(cat.KIND_PHONE)
        self.phone_search = widgets.SearchBox("جستجوی گوشی…")
        self.phone_search.textChanged.connect(lambda _t: self.render())
        holder.layout().addWidget(self.phone_search)
        box.addWidget(holder)
        self.phones_table = widgets.DataTable(PHONE_HEADERS, selectable_rows=True, key="site_phones")
        self.phones_table.set_empty_state("هنوز گوشی‌ای نیست",
                                          "در «انتشار و پشتیبان»، «خواندن از سایت» را بزنید.", "file")
        self.phones_table.setMinimumHeight(320)
        self.phones_table.row_activated.connect(lambda _r: self._edit_phone())
        box.addWidget(self.phones_table, 1)
        self.phones_summary = widgets.label("", name="Muted")
        box.addWidget(self.phones_summary)
        return panel

    def _accessories_panel(self) -> QWidget:
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(10, 0, 10, 0)   # never flush against the tree
        holder, (self.edit_accessory_button, self.delete_accessory_button) = \
            self._item_bar(cat.KIND_ACCESSORY)
        self.accessory_search = widgets.SearchBox("جستجوی لوازم جانبی…")
        self.accessory_search.textChanged.connect(lambda _t: self.render())
        holder.layout().addWidget(self.accessory_search)
        box.addWidget(holder)
        self.accessories_table = widgets.DataTable(ACCESSORY_HEADERS, selectable_rows=True,
                                                   key="site_accessories")
        self.accessories_table.set_empty_state("در این دسته هنوز کالایی نیست",
                                               "«افزودن از PDF…» یا «افزودن دستی» را بزنید.", "box")
        self.accessories_table.setMinimumHeight(320)
        self.accessories_table.row_activated.connect(lambda _r: self._edit_accessory())
        box.addWidget(self.accessories_table, 1)
        self.accessories_summary = widgets.label("", name="Muted")
        box.addWidget(self.accessories_summary)
        return panel

    def _publish_tab(self) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)
        box.addWidget(widgets.label("تغییرهای منتشرنشده — خودکار به‌روز می‌شود؛ همین‌ها با «انتشار» "
                                    "در سایت دیده می‌شود:", bold=True, wrap=True))
        self.preview_box = QPlainTextEdit()
        self.preview_box.setReadOnly(True)
        self.preview_box.setMinimumHeight(150)
        box.addWidget(self.preview_box)
        self.publish_state = widgets.label("", name="Muted", wrap=True)
        box.addWidget(self.publish_state)
        actions = QWidget()
        flow = widgets.FlowLayout(actions, spacing=8)
        self.browser_button = widgets.button("پیش‌نمایش در مرورگر", icon_name="globe",
                                             on_click=self._preview_browser)
        self.publish_button = widgets.button("انتشار در سایت", icon_name="check",
                                             variant="primary", on_click=self._publish)
        self.rollback_button = widgets.button("برگرداندن انتشار قبلی", icon_name="refresh",
                                              on_click=self._rollback)
        for b in (self.publish_button, self.browser_button, self.rollback_button):
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

    #: v2.14.0 the branch shown next to the tree: (kind, key)
    _node: tuple[str, str] = (NODE_PHONES, "")

    def _fill_tree(self, data: dict, phones: list[dict], accessories: list[dict]) -> None:
        tree = self.tree
        tree.blockSignals(True)
        expanded = {tuple(i.data(0, Qt.ItemDataRole.UserRole)) for i in self._tree_items()
                    if i.isExpanded()}
        first = not tree.topLevelItemCount()
        tree.clear()

        def node(parent, text: str, kind: str, key: str = "") -> QTreeWidgetItem:
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.ItemDataRole.UserRole, [kind, key])
            item.setToolTip(0, text)
            (parent.addChild if isinstance(parent, QTreeWidgetItem) else tree.addTopLevelItem)(item)
            return item

        root = node(tree, f"گوشی‌ها ({format_int(len(phones))})", NODE_PHONES)
        for brand in data["brands"]:
            models = [p for p in phones if p["brand"] == brand["key"]]
            branch = node(root, f"{brand['name']} ({format_int(len(models))})", NODE_BRAND,
                          brand["key"])
            for phone in models:
                node(branch, phone["name"] + (" — پنهان" if phone["hidden"] else ""),
                     NODE_PHONE, phone["code"])
        root2 = node(tree, f"لوازم جانبی ({format_int(len(accessories))})", NODE_ACCESSORIES)
        for group in cat.clean_groups(data.get("groups")):
            rows = [a for a in accessories if a["group"] == group["key"]]
            branch = node(root2, f"{group['name']} ({format_int(len(rows))})", NODE_GROUP,
                          group["key"])
            for row in rows:
                node(branch, row["name"] + (" — پنهان" if row["hidden"] else ""),
                     NODE_ACCESSORY, row["code"])
        current = None
        for item in self._tree_items():
            key = tuple(item.data(0, Qt.ItemDataRole.UserRole))
            if key in expanded or (first and key[0] in (NODE_PHONES, NODE_ACCESSORIES)):
                item.setExpanded(True)
            if key == tuple(self._node):
                current = item
        tree.setCurrentItem(current or root)
        tree.blockSignals(False)

    def _tree_items(self) -> list[QTreeWidgetItem]:
        out, stack = [], [self.tree.topLevelItem(n) for n in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            out.append(item)
            stack[0:0] = [item.child(n) for n in range(item.childCount())]
        return out

    def _node_changed(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        kind, key = item.data(0, Qt.ItemDataRole.UserRole)
        self._node = (kind, key)
        self.render()

    def _branch(self) -> tuple[str, str]:
        """(category, branch key) of the chosen node: the brand or the accessory
        category; "" for a top node."""
        kind, key = self._node
        if kind in (NODE_PHONES, NODE_BRAND, NODE_PHONE):
            brand = key if kind == NODE_BRAND else ""
            if kind == NODE_PHONE:
                brand = (self.store.get(key) or {}).get("brand", "")
            return cat.KIND_PHONE, brand
        group = key if kind == NODE_GROUP else ""
        if kind == NODE_ACCESSORY:
            group = (self.store.get(key) or {}).get("group", "")
        return cat.KIND_ACCESSORY, group

    def _pill(self, item: dict) -> QWidget:
        pill = widgets.TogglePill("پنهان" if item["hidden"] else "نمایش",
                                  "warning" if item["hidden"] else "success",
                                  tooltip="با کلیک در سایت نمایش داده یا پنهان می‌شود")
        pill.setEnabled(self.can_manage)
        code = item["code"]
        pill.clicked.connect(lambda: self._toggle_code(code))
        return widgets.pill_cell(pill)

    def render(self) -> None:
        data = self.store.load()
        phones = [i for i in data["items"] if i["category"] == cat.KIND_PHONE]
        accessories = [i for i in data["items"] if i["category"] == cat.KIND_ACCESSORY]
        brands = {b["key"]: b["name"] for b in data["brands"]}
        groups = {g["key"]: g["name"] for g in cat.clean_groups(data.get("groups"))}
        self._fill_tree(data, phones, accessories)
        category, branch = self._branch()
        kind, key = self._node
        self.stack.setCurrentIndex(0 if category == cat.KIND_PHONE else 1)
        self.pdf_button.setEnabled(self.can_manage and category == cat.KIND_ACCESSORY
                                   and bool(branch))
        self.rename_button.setEnabled(self.can_manage and bool(branch))
        self.undelete_button.setEnabled(self.can_manage and bool(self.store.recently_deleted()))
        if category == cat.KIND_PHONE:
            where = f"«{brands.get(branch, branch)}»" if branch else "همهٔ برندها"
            hint = f"گوشی‌های {where}."
            if branch and branch not in SITE_BRAND_PAGES:
                hint += " سایت هنوز برای این برند صفحه ندارد؛ گوشی‌هایش فقط همین‌جا نگه داشته می‌شود."
        else:
            hint = (f"لوازم جانبی «{groups.get(branch, branch)}» — «افزودن از PDF…» کالاها را به "
                    "همین دسته می‌برد." if branch else
                    "یک دسته را در درخت انتخاب کنید تا «افزودن از PDF…» فعال شود.")
        self.branch_hint.setText(hint)

        self._phones = [p for p in phones if (not branch or category != cat.KIND_PHONE
                                              or p["brand"] == branch)
                        and matches(p, self.phone_search.text())]
        table = self.phones_table
        table.setRowCount(0)
        for item in self._phones:
            i = table.rowCount()
            table.insertRow(i)
            table.set_cell(i, 0, brands.get(item["brand"], item["brand"] or "—"))
            table.set_cell(i, 1, item["name"], bold=True)
            table.set_cell(i, 2, "، ".join(c["name"] for c in item["colors"]) or "—")
            table.set_cell(i, 3, photo_state(self.store, item))
            table.set_widget(i, 4, self._pill(item))
            table.set_row_key(i, item["code"])
        table._refresh_states()
        self._accessories = [a for a in accessories if (not branch or category != cat.KIND_ACCESSORY
                                                        or a["group"] == branch)
                             and matches(a, self.accessory_search.text())]
        table = self.accessories_table
        table.setRowCount(0)
        for item in self._accessories:
            i = table.rowCount()
            table.insertRow(i)
            table.set_cell(i, 0, groups.get(item["group"], "سایر"))
            table.set_cell(i, 1, item["name"], bold=True)
            table.set_cell(i, 2, item["brand_name"] or "—")
            table.set_cell(i, 3, photo_state(self.store, item))
            table.set_widget(i, 4, self._pill(item))
            table.set_row_key(i, item["code"])
        table._refresh_states()
        if kind in (NODE_PHONE, NODE_ACCESSORY):
            target = self.phones_table if kind == NODE_PHONE else self.accessories_table
            target.select_key(key)
        self.phones_summary.setText(count_text(self.store.counts(cat.KIND_PHONE), "گوشی"))
        self.accessories_summary.setText(count_text(self.store.counts(cat.KIND_ACCESSORY),
                                                    "لوازم جانبی"))
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
            self.banner.setText(f"{count_text(self.store.counts(cat.KIND_PHONE), 'گوشی')} و "
                                f"{count_text(self.store.counts(cat.KIND_ACCESSORY), 'لوازم جانبی')}"
                                f" — {changes}")
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
    def _add_manual(self) -> None:
        category, branch = self._branch()
        if category == cat.KIND_PHONE:
            self._add_phone(branch)
        else:
            self._add_accessory(branch)

    def _add_phone(self, brand: str = "") -> None:
        dialog = PhoneDialog(self.store, parent=self)
        if brand:
            dialog.brand.setCurrentIndex(max(0, dialog.brand.findData(brand)))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.notify_success("گوشی اضافه شد؛ با «انتشار در سایت» در سایت دیده می‌شود.")
        self.render()

    def _edit_phone(self) -> None:
        item = self._selected(self.phones_table, self._phones)
        if item and self.can_manage and PhoneDialog(self.store, item, parent=self).exec():
            self.notify_success("ذخیره شد.")
        self.render()

    def _add_accessory(self, group: str = "") -> None:
        dialog = AccessoryDialog(self.store, parent=self)
        if group:
            dialog.group.setCurrentIndex(max(0, dialog.group.findData(group)))
        if dialog.exec() == QDialog.DialogCode.Accepted:
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
        if item is not None:
            self._toggle_code(item["code"])

    def _toggle_code(self, code: str) -> None:
        """v2.14.0: a click on the «نمایش/پنهان» pill of a row."""
        item = self.store.get(code)
        if item is None or not self.can_manage:
            return
        self.store.set_hidden(code, not item["hidden"])
        self.notify_success(f"«{item['name']}» " + ("در سایت نمایش داده می‌شود." if item["hidden"]
                                                     else "در سایت پنهان می‌شود."))
        self.render()

    def _delete(self, kind: str) -> None:
        table = self.phones_table if kind == cat.KIND_PHONE else self.accessories_table
        item = self._selected(table, self._phones if kind == cat.KIND_PHONE else self._accessories)
        if item is None:
            return
        if not widgets.confirm(self, "حذف", f"«{item['name']}» حذف شود؟" + NL + NL +
                               "با «انتشار در سایت» از سایت هم برداشته می‌شود. تا ۴۸ ساعت با "
                               "«برگرداندن حذف‌شده‌ها…» (یا «برگرداندن انتشار قبلی») برمی‌گردد.",
                               confirm_text="حذف", kind="warning"):
            return
        self.store.delete(item["code"])
        self.notify_success(f"«{item['name']}» حذف شد.")
        self.render()

    def _undelete(self) -> None:
        entries = self.store.recently_deleted()
        if not entries:
            self.notify_warning("در ۴۸ ساعت گذشته چیزی حذف نشده است.")
            return
        names = [f"{e['item'].get('name')} — {format_shamsi(e.get('at'))}" for e in entries]
        choice, ok = QInputDialog.getItem(self, "برگرداندن حذف‌شده‌ها", "کدام برگردد؟", names, 0,
                                          False)
        if not ok or choice not in names:
            return
        entry = entries[names.index(choice)]
        if self.store.undelete(entry["item"].get("code", "")):
            self.notify_success(f"«{entry['item'].get('name')}» برگشت.")
        else:
            self.notify_warning("برنگشت؛ کالایی با همین کد هست.")
        self.render()

    # ---- branches ------------------------------------------------------------------------
    def _ask_name(self, title: str, label: str, text: str = "") -> str:
        value, ok = QInputDialog.getText(self, title, label, QLineEdit.EchoMode.Normal, text)
        return " ".join(value.split()) if ok else ""

    def _new_branch(self) -> None:
        category, _branch = self._branch()
        phone = category == cat.KIND_PHONE
        name = self._ask_name("زیرشاخهٔ تازه", "نام برند تازه (انگلیسی، مثلاً Honor):" if phone
                              else "نام دستهٔ تازهٔ لوازم جانبی (مثلاً ساعت هوشمند):")
        if not name:
            return
        try:
            key = self.store.add_brand(name) if phone else self.store.add_group(name)
        except SiteDataError as exc:
            widgets.error(self, "زیرشاخهٔ تازه", str(exc))
            return
        self._node = (NODE_BRAND if phone else NODE_GROUP, key)
        self.notify_success(f"«{name}» ساخته شد.")
        self.render()

    def _rename_branch(self) -> None:
        category, branch = self._branch()
        if not branch:
            self.notify_warning("یک برند یا دسته را در درخت انتخاب کنید.")
            return
        phone = category == cat.KIND_PHONE
        current = next((b["name"] for b in self.store.brands() if b["key"] == branch), "") \
            if phone else self.store.group_name(branch)
        name = self._ask_name("تغییر نام", "نام تازه:", current)
        if not name or name == current:
            return
        try:
            (self.store.rename_brand if phone else self.store.rename_group)(branch, name)
        except SiteDataError as exc:
            widgets.error(self, "تغییر نام", str(exc))
            return
        self.notify_success("نام عوض شد.")
        self.render()

    def _read_pdf(self) -> None:
        category, group = self._branch()
        if category != cat.KIND_ACCESSORY or not group:
            self.notify_warning("اول یک دستهٔ لوازم جانبی را در درخت انتخاب کنید؛ کالاهای PDF به "
                                "همان دسته می‌روند.")
            return
        paths_, _f = QFileDialog.getOpenFileNames(self, "انتخاب PDF (یک یا چند فایل)", "",
                                                  "PDF (*.pdf)")
        for path in paths_:
            try:
                data = Path(path).read_bytes()
            except OSError:
                self.notify_error(f"«{Path(path).name}» خوانده نشد.")
                continue
            dialog = PdfImportDialog(self.store, group, data, file_name=Path(path).name, parent=self)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            self.render()
            if accepted:
                widgets.success(self, "افزودن از PDF", dialog.result_text())
            else:
                break

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
