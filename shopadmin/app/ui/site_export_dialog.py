"""v2.10.0 «خروجی کاتالوگ برای سایت» — مدل‌ها، رنگ‌ها، مشخصات و عکس‌های سایت از سرور فروشگاه.

* **پیش‌نمایش**: پیش از هر خروجی، سرور می‌گوید نسبت به خروجی قبلی چه مدلی تازه / تغییرکرده /
  حذف‌شده است، چه عکسی تازه است و چه هشدارهایی هست (عکس نیست، برند صفحه ندارد…).
* **ذخیرهٔ فایل خروجی**: یک zip با ``catalog.json`` و پوشهٔ ``images``؛ محتوایش در
  ``assets/catalog/`` سایت قرار می‌گیرد. هیچ چیز از اینجا منتشر نمی‌شود.
* **زمان‌بندی** (اختیاری، فقط مدیر سرور): هر روز پس از ساعتی که می‌گویید، اگر چیزی عوض شده
  باشد، خروجی در پوشه‌ای روی خود سرور نوشته می‌شود.
* **خواندن از پوشهٔ سایت**: یک بار، مدل‌ها و عکس‌های فعلی سایت (``assets/products.js``،
  ``assets/site.js``، ``assets/products/*.jpg``) به سرور فرستاده می‌شود.
* **PDF لوازم جانبی**: نام، مشخصات و عکس هر کالا از PDF خوانده می‌شود؛ هر کدام را تیک بزنید
  اضافه می‌شود.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressDialog,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..persian import format_int, format_shamsi, to_persian_digits
from ..permissions import CATALOG_MANAGE, SERVER_MANAGE
from . import theme, widgets
from .rtl import mark_ltr

NL = chr(10)
GROUPS_FA = {"case": "قاب و کاور", "charger": "شارژر و کابل", "headphones": "هدفون و هندزفری",
             "powerbank": "پاوربانک", "other": "سایر لوازم جانبی"}
TIERS = ("پرچمدار", "میان‌رده", "اقتصادی", "پرفروش")
MAX_LINES = 40


# ---- pure helpers (tested without a window) ----------------------------------------
def _names(rows: list[dict]) -> str:
    shown = "، ".join(str(r.get("name") or r.get("code")) for r in rows[:MAX_LINES])
    if len(rows) > MAX_LINES:
        shown += f" و {format_int(len(rows) - MAX_LINES)} مورد دیگر"
    return shown


def change_lines(preview: dict) -> list[str]:
    """The preview in short Persian lines (what the site would get)."""
    counts = preview.get("counts") or {}
    change = preview.get("changes") or {}
    lines = [f"در خروجی: {format_int(counts.get('phones') or 0)} گوشی، "
             f"{format_int(counts.get('accessories') or 0)} لوازم جانبی، "
             f"{format_int(counts.get('images') or 0)} عکس."]
    if counts.get("skipped"):
        lines.append(f"{format_int(counts['skipped'])} مدل هنوز اطلاعات سایت ندارد و در خروجی نیست.")
    if change.get("first"):
        lines.append("این نخستین خروجی است؛ همهٔ مدل‌ها تازه حساب می‌شوند.")
    for key, title in (("added", "تازه"), ("changed", "تغییرکرده"), ("removed", "حذف از سایت")):
        rows = change.get(key) or []
        if rows and not (key == "added" and change.get("first")):
            lines.append(f"{title} ({format_int(len(rows))}): {_names(rows)}")
    new_images, changed_images = change.get("images_new") or [], change.get("images_changed") or []
    if new_images or changed_images:
        lines.append(f"عکس: {format_int(len(new_images))} تازه، "
                     f"{format_int(len(changed_images))} عوض‌شده.")
    if change.get("brands_changed"):
        lines.append("متن برندها عوض شده است.")
    if not preview.get("has_changes"):
        lines.append("نسبت به خروجی قبلی تغییری نیست.")
    return lines


def warning_lines(preview: dict) -> list[str]:
    return [f"• {w.get('text')}" for w in (preview.get("warnings") or [])]


def last_export_fa(last: Optional[dict]) -> str:
    if not last:
        return "هنوز خروجی‌ای ساخته نشده است."
    when = format_shamsi(last.get("at"))
    if not last.get("ok"):
        return f"خروجی خودکار ناموفق بود ({when}): {last.get('error') or '—'}"
    where = "پوشهٔ سرور" if last.get("where") == "folder" else "فایل zip"
    return (f"آخرین خروجی: {when} در {where} — {format_int(last.get('items') or 0)} مدل، "
            f"{format_int(last.get('images') or 0)} عکس")


def colors_to_text(colors: list[dict]) -> str:
    """One colour per line: «نام | فایل عکس | #رنگ» (the last two optional)."""
    lines = []
    for c in colors or []:
        parts = [str(c.get("name") or "")]
        if c.get("image") or c.get("hex"):
            parts.append(str(c.get("image") or ""))
        if c.get("hex"):
            parts.append(str(c["hex"]))
        lines.append(" | ".join(parts))
    return NL.join(lines)


def parse_colors_text(text: str) -> list[dict]:
    out = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if not parts[0]:
            continue
        out.append({"name": parts[0][:40],
                    "image": (parts[1] if len(parts) > 1 else "").lower()[:130],
                    "hex": (parts[2] if len(parts) > 2 else "")[:7]})
    return out[:12]


def specs_to_text(specs: list) -> str:
    return NL.join(f"{k}: {v}" for k, v in specs or [])


def parse_specs_text(text: str) -> list[list[str]]:
    out = []
    for line in (text or "").splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            key, sep, value = line.partition("：")
        if sep and key.strip() and value.strip():
            out.append([key.strip()[:40], value.strip()[:160]])
    return out[:20]


def site_folder_sources(folder: str | Path) -> tuple[str, str, Path]:
    """(products.js, site.js, photo folder) of a copy of the site. Raises
    ValueError with a Persian reason."""
    root = Path(folder)
    products = root / "assets" / "products.js"
    if not products.is_file():
        raise ValueError("در این پوشه assets/products.js نیست؛ پوشهٔ اصلی سایت را انتخاب کنید.")
    site = root / "assets" / "site.js"
    return (products.read_text(encoding="utf-8"),
            site.read_text(encoding="utf-8") if site.is_file() else "",
            root / "assets" / "products")


def photos_to_send(names: list[str], folder: Path) -> list[tuple[str, Path]]:
    """The asked photos that exist in the site's photo folder."""
    return [(name, folder / name) for name in names if (folder / name).is_file()]


def error_text(exc: Exception) -> str:
    return str(exc) or "انجام نشد؛ دوباره امتحان کنید."


def _text_box(min_height: int = 110) -> QPlainTextEdit:
    box = QPlainTextEdit()
    box.setReadOnly(True)
    box.setMinimumHeight(min_height)
    return box


# ---- the main dialog -------------------------------------------------------------
class SiteExportDialog(widgets.ResponsiveDialog):
    """پیش‌نمایش و ساخت خروجی کاتالوگ سایت، زمان‌بندی و ابزارهای ورود."""

    def __init__(self, context, parent: QWidget | None = None, *, load: bool = True) -> None:
        super().__init__(parent)
        self.context = context
        self.preview: dict = {}
        self.can_manage = context.can(CATALOG_MANAGE)
        self.can_server = context.can(SERVER_MANAGE)
        self.setWindowTitle("خروجی کاتالوگ برای سایت")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(660)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(widgets.label("خروجی کاتالوگ برای سایت", size=15, bold=True))
        root.addWidget(widgets.label(
            "مدل‌ها، رنگ‌ها، مشخصات و عکس‌ها در یک فایل (catalog.json و پوشهٔ images) برای سایت "
            "ساخته می‌شود. قیمت، کد کالا و هیچ اطلاعات خصوصی‌ای در آن نیست. فایل به‌طور خودکار "
            "منتشر نمی‌شود؛ گذاشتن آن در سایت کار جداگانه‌ای است.", name="Muted", wrap=True))

        self.summary = widgets.label("", wrap=True, bold=True)
        root.addWidget(self.summary)
        self.changes = _text_box(120)
        root.addWidget(self.changes)
        root.addWidget(widgets.label("هشدارها:", bold=True))
        self.warnings = _text_box(90)
        root.addWidget(self.warnings)

        tools_holder = QWidget()
        tools = widgets.FlowLayout(tools_holder, spacing=8)
        self.seed_button = widgets.button("خواندن از پوشهٔ سایت…", icon_name="folder",
                                          on_click=self._seed_from_folder)
        self.pdf_button = widgets.button("خواندن PDF لوازم جانبی…", icon_name="file",
                                         on_click=self._read_pdf)
        self.refresh_button = widgets.button("تازه‌سازی", icon_name="refresh",
                                             on_click=self.load)
        for b in (self.seed_button, self.pdf_button):
            b.setEnabled(self.can_manage)
        for b in (self.seed_button, self.pdf_button, self.refresh_button):
            tools.addWidget(b)
        root.addWidget(tools_holder)

        schedule = widgets.Panel()
        schedule.body.addWidget(widgets.label("خروجی خودکار روزانه روی سرور (اختیاری)", bold=True))
        row = QHBoxLayout()
        self.schedule_check = QCheckBox("هر روز، اگر چیزی عوض شده باشد، بعد از ساعت")
        self.hour_input = QSpinBox()
        self.hour_input.setRange(0, 23)
        self.hour_input.setValue(6)
        row.addWidget(self.schedule_check)
        row.addWidget(self.hour_input)
        row.addStretch(1)
        schedule.body.addLayout(row)
        folder_row = QHBoxLayout()
        folder_row.addWidget(widgets.label("پوشه روی سرور:"))
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("D:\\SiteCatalog")
        mark_ltr(self.folder_input)
        folder_row.addWidget(self.folder_input, 1)
        schedule.body.addLayout(folder_row)
        schedule_buttons = QWidget()
        sb = widgets.FlowLayout(schedule_buttons, spacing=8)
        self.save_schedule_button = widgets.button("ذخیرهٔ زمان‌بندی", icon_name="save",
                                                   on_click=self._save_schedule)
        self.folder_now_button = widgets.button("نوشتن در همین پوشه اکنون", icon_name="server",
                                                on_click=self._export_folder)
        for b in (self.save_schedule_button, self.folder_now_button):
            b.setEnabled(self.can_server)
            sb.addWidget(b)
        schedule.body.addWidget(schedule_buttons)
        self.last_label = widgets.label("", name="Muted", wrap=True)
        schedule.body.addWidget(self.last_label)
        if not self.can_server:
            schedule.body.addWidget(widgets.label("زمان‌بندی فقط با دسترسی «تنظیمات سرور» "
                                                  "تغییر می‌کند.", name="Muted", wrap=True))
        root.addWidget(schedule)

        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        root.addWidget(self.error_label)
        self.export_button = widgets.button("ذخیرهٔ فایل خروجی…", icon_name="download",
                                            variant="primary", on_click=self._export_zip)
        self.export_button.setEnabled(self.can_manage)
        root.addLayout(widgets.footer(self.export_button,
                                      close=widgets.button("بستن", on_click=self.reject)))
        if load:
            self.load()

    # ---- data ------------------------------------------------------------------
    def load(self) -> None:
        self.error_label.setText("")
        try:
            preview = self.context.api.site_catalog_preview()
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.error_label.setText(error_text(exc))
            return
        self.show_preview(preview)

    def show_preview(self, preview: dict) -> None:
        self.preview = dict(preview or {})
        problems = self.preview.get("problems") or []
        self.summary.setText("آمادهٔ خروجی است." if not problems else
                             "خروجی هنوز ساخته نمی‌شود: " + "، ".join(problems[:3]))
        self.summary.setStyleSheet(f"color: {theme.SUCCESS_DARK if not problems else theme.DANGER};")
        self.changes.setPlainText(NL.join(change_lines(self.preview)))
        warnings = warning_lines(self.preview)
        self.warnings.setPlainText(NL.join(warnings) if warnings else "هشداری نیست.")
        schedule = self.preview.get("schedule") or {}
        self.schedule_check.setChecked(bool(schedule.get("enabled")))
        self.hour_input.setValue(int(schedule.get("hour") or 6))
        self.folder_input.setText(str(schedule.get("folder") or ""))
        self.last_label.setText(last_export_fa(self.preview.get("last")))
        self.export_button.setEnabled(self.can_manage and not problems)

    # ---- export ----------------------------------------------------------------
    def _export_zip(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "ذخیرهٔ خروجی کاتالوگ سایت",
                                                    "site-catalog.zip", "zip (*.zip)")
        if not path:
            return
        try:
            data = self.context.api.site_catalog_export_zip()
            Path(path).write_bytes(data)
        except OSError:
            self.error_label.setText("فایل در این پوشه ذخیره نشد؛ پوشهٔ دیگری انتخاب کنید.")
            return
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.error_label.setText(error_text(exc))
            return
        widgets.success(self, "خروجی ساخته شد",
                        "فایل ذخیره شد. محتوای آن (catalog.json و پوشهٔ images) در پوشهٔ "
                        "assets/catalog سایت قرار می‌گیرد.")
        self.load()

    def _export_folder(self) -> None:
        folder = self.folder_input.text().strip()
        try:
            summary = self.context.api.site_catalog_export_folder(folder)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.error_label.setText(error_text(exc))
            return
        widgets.success(self, "خروجی نوشته شد",
                        f"در پوشهٔ سرور نوشته شد ({format_int(summary.get('images_written') or 0)} "
                        "عکس تازه).")
        self.load()

    def _save_schedule(self) -> None:
        try:
            self.context.api.set_site_catalog_schedule(self.schedule_check.isChecked(),
                                                       self.hour_input.value(),
                                                       self.folder_input.text().strip())
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.error_label.setText(error_text(exc))
            return
        self.error_label.setText("")
        widgets.success(self, "زمان‌بندی ذخیره شد",
                        "خروجی خودکار روزانه روشن شد." if self.schedule_check.isChecked()
                        else "خروجی خودکار خاموش شد.")

    # ---- tools -----------------------------------------------------------------
    def _seed_from_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "پوشهٔ اصلی سایت (همان که index.html دارد)")
        if folder:
            self.seed_from(folder)

    def seed_from(self, folder: str) -> Optional[dict]:
        """Send the site's models, then the photos the server still needs."""
        self.error_label.setText("")
        try:
            products_js, site_js, photo_dir = site_folder_sources(folder)
            result = self.context.api.seed_site_catalog(products_js, site_js)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.error_label.setText(error_text(exc))
            return None
        photos = photos_to_send(list(result.get("images_needed") or []), photo_dir)
        failed = self._upload(photos)
        missing = len(result.get("images_needed") or []) - len(photos)
        text = (f"{format_int(result.get('models') or 0)} مدل خوانده شد "
                f"({format_int(result.get('added') or 0)} تازه)، "
                f"{format_int(len(photos) - failed)} عکس فرستاده شد.")
        if result.get("kept"):
            text += (f" اطلاعات سایتِ {format_int(result['kept'])} مدل که قبلاً در سرور فروشگاه "
                     "بود دست نخورد.")
        if missing or failed:
            text += f" {format_int(missing + failed)} عکس فرستاده نشد (در پوشه نبود یا سالم نبود)."
        widgets.success(self, "خواندن از پوشهٔ سایت", text)
        self.load()
        return result

    def _upload(self, photos: list[tuple[str, Path]]) -> int:
        """Upload photos with a progress window; returns how many failed."""
        failed = 0
        progress = QProgressDialog("در حال فرستادن عکس‌ها…", "توقف", 0, len(photos), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(400)
        for n, (name, path) in enumerate(photos):
            if progress.wasCanceled():
                failed += len(photos) - n
                break
            progress.setValue(n)
            QApplication.processEvents()
            try:
                self.context.api.upload_site_image(name, path.read_bytes())
            except Exception:  # noqa: BLE001 - counted and reported once
                failed += 1
        progress.setValue(len(photos))
        return failed

    def _read_pdf(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "انتخاب PDF لوازم جانبی", "", "PDF (*.pdf)")
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError:
            self.error_label.setText("این فایل خوانده نشد.")
            return
        dialog = AccessoryPdfDialog(self.context, data, parent=self)
        if dialog.exec():
            self.load()


# ---- one model's site data ---------------------------------------------------------
class SiteModelDialog(widgets.ResponsiveDialog):
    """اطلاعات سایتِ یک مدل: نمایش در سایت، رده، سال، رنگ‌ها، مشخصات و عکس‌ها."""

    def __init__(self, context, model_id: int, parent: QWidget | None = None,
                 payload: Optional[dict] = None) -> None:
        super().__init__(parent)
        self.context = context
        self.model_id = int(model_id)
        self.setWindowTitle("اطلاعات سایت")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(600)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        self.title = widgets.label("", size=14, bold=True, wrap=True)
        root.addWidget(self.title)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)

        self.published = QCheckBox("در سایت نمایش داده شود")
        root.addWidget(self.published)
        row = QHBoxLayout()
        row.addWidget(widgets.label("رده:"))
        self.tier = QComboBox()
        self.tier.setEditable(True)
        self.tier.addItems(TIERS)
        row.addWidget(self.tier, 1)
        row.addWidget(widgets.label("سال عرضه:"))
        self.year = QSpinBox()
        self.year.setRange(2000, 2100)
        self.year.setValue(2026)
        row.addWidget(self.year)
        root.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(widgets.label("نوع لوازم جانبی:"))
        self.group = QComboBox()
        self.group.addItem("— (گوشی)", "")
        for key, title in GROUPS_FA.items():
            self.group.addItem(title, key)
        row2.addWidget(self.group, 1)
        row2.addWidget(widgets.label("عکس کارت:"))
        self.card_image = QComboBox()
        self.card_image.setEditable(True)
        mark_ltr(self.card_image)
        row2.addWidget(self.card_image, 1)
        root.addLayout(row2)

        root.addWidget(widgets.label("رنگ‌ها — هر رنگ در یک خط: «نام | فایل عکس | #رنگ»",
                                     bold=True, wrap=True))
        self.colors = QPlainTextEdit()
        self.colors.setMinimumHeight(100)
        root.addWidget(self.colors)
        root.addWidget(widgets.label("مشخصات — هر مورد در یک خط: «عنوان: مقدار»", bold=True,
                                     wrap=True))
        self.specs = QPlainTextEdit()
        self.specs.setMinimumHeight(110)
        root.addWidget(self.specs)
        root.addWidget(widgets.label(
            "نام فایل عکس فقط حروف کوچک انگلیسی، عدد و - باشد (مثلاً iphone-17-black.jpg). "
            "قیمت هیچ‌وقت در سایت نوشته نمی‌شود.", name="Muted", wrap=True))
        root.addWidget(self.error_label)
        self.photo_button = widgets.button("افزودن عکس…", icon_name="plus",
                                           on_click=self._add_photos)
        save = widgets.button("ذخیره", icon_name="check", variant="primary", on_click=self._save)
        can = context.can(CATALOG_MANAGE)
        self.photo_button.setEnabled(can)
        save.setEnabled(can)
        root.addLayout(widgets.footer(self.photo_button, save,
                                      close=widgets.button("انصراف", on_click=self.reject)))
        if payload is None:
            try:
                payload = context.api.site_model(self.model_id)
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self.error_label.setText(error_text(exc))
                payload = {}
        self.fill(payload)

    def fill(self, payload: dict) -> None:
        model = payload.get("model") or {}
        site = payload.get("site") or {}
        self.title.setText(f"اطلاعات سایت «{model.get('name') or ''}» — کد مدل: "
                           f"{model.get('slug') or ''}")
        if not payload.get("site"):
            self.error_label.setText("این مدل هنوز اطلاعات سایت ندارد؛ با «ذخیره» در خروجی "
                                     "سایت می‌آید.")
        self.published.setChecked(site.get("published", True) is not False)
        self.tier.setCurrentText(str(site.get("tier") or ""))
        if site.get("release_year"):
            self.year.setValue(int(site["release_year"]))
        index = self.group.findData(site.get("group") or "")
        self.group.setCurrentIndex(max(0, index))
        self.card_image.clear()
        self.card_image.addItem("")
        self.card_image.addItems(list(payload.get("images") or []))
        self.card_image.setCurrentText(str(site.get("image") or ""))
        self.colors.setPlainText(colors_to_text(site.get("colors") or []))
        self.specs.setPlainText(specs_to_text(site.get("specs") or []))
        self._site = site

    def data(self) -> dict:
        site = dict(getattr(self, "_site", {}) or {})
        site.update({
            "published": self.published.isChecked(),
            "tier": self.tier.currentText().strip()[:30],
            "release_year": int(self.year.value()),
            "image": self.card_image.currentText().strip().lower()[:130],
            "colors": parse_colors_text(self.colors.toPlainText()),
            "specs": parse_specs_text(self.specs.toPlainText()),
            "group": self.group.currentData() or "",
        })
        site.setdefault("price_state", "")
        return {k: site[k] for k in ("published", "tier", "release_year", "price_state", "image",
                                     "colors", "specs", "group", "brand_key", "brand_name")
                if k in site}

    def _save(self) -> None:
        try:
            self.context.api.save_site_model(self.model_id, self.data())
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.error_label.setText(error_text(exc))
            return
        self.accept()

    def _add_photos(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(self, "عکس‌های مدل", "",
                                                      "عکس (*.jpg *.jpeg *.png *.webp)")
        failed = []
        for path in paths:
            name = Path(path).name.lower()
            try:
                self.context.api.upload_site_image(name, Path(path).read_bytes())
            except Exception as exc:  # noqa: BLE001 - listed below
                failed.append(f"{name}: {error_text(exc)}")
                continue
            if self.card_image.findText(name) < 0:
                self.card_image.addItem(name)
        self.error_label.setText(NL.join(failed))


# ---- accessory PDF -----------------------------------------------------------------
class AccessoryPdfDialog(widgets.ResponsiveDialog):
    """کالاهای یک PDF لوازم جانبی؛ تیک‌خورده‌ها به مدل‌های سایت اضافه می‌شوند."""

    def __init__(self, context, data: bytes, parent: QWidget | None = None,
                 payload: Optional[dict] = None) -> None:
        super().__init__(parent)
        self.context = context
        self.data = data
        self.setWindowTitle("لوازم جانبی از PDF")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(580)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(widgets.label("کالاهای این PDF", size=14, bold=True))
        root.addWidget(widgets.label(
            "هر کالایی را که درست خوانده شده تیک بزنید؛ با نام، مشخصات و عکسش به «مدل‌های سایت» "
            "اضافه می‌شود و بعد می‌توانید «اطلاعات سایت» آن را ویرایش کنید.",
            name="Muted", wrap=True))
        self.list = QListWidget()
        self.list.setMinimumHeight(240)
        root.addWidget(self.list)
        self.error_label = widgets.label("", color=theme.DANGER, wrap=True)
        root.addWidget(self.error_label)
        self.add_button = widgets.button("افزودن تیک‌خورده‌ها", icon_name="plus",
                                         variant="primary", on_click=self._add)
        root.addLayout(widgets.footer(self.add_button,
                                      close=widgets.button("انصراف", on_click=self.reject)))
        if payload is None:
            try:
                payload = context.api.read_accessory_pdf(data)
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self.error_label.setText(error_text(exc))
                payload = {}
        self.fill(payload)

    def fill(self, payload: dict) -> None:
        self.list.clear()
        items = list(payload.get("items") or [])
        for item in items:
            text = (f"{item.get('name')} — {GROUPS_FA.get(item.get('group'), 'سایر')} — "
                    f"{format_int(len(item.get('specs') or []))} مشخصه، "
                    f"{format_int(item.get('image_count') or 0)} عکس — صفحهٔ "
                    f"{to_persian_digits(item.get('page'))}")
            entry = QListWidgetItem(text)
            entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            entry.setCheckState(Qt.CheckState.Checked)
            entry.setData(Qt.ItemDataRole.UserRole, item.get("code"))
            entry.setToolTip(NL.join(f"{k}: {v}" for k, v in item.get("specs") or []))
            self.list.addItem(entry)
        if payload and not items:
            self.error_label.setText("کالایی در این PDF پیدا نشد.")
        self.add_button.setEnabled(bool(items) and self.context.can(CATALOG_MANAGE))

    def checked_codes(self) -> list[str]:
        return [str(self.list.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def _add(self) -> None:
        codes = self.checked_codes()
        if not codes:
            self.error_label.setText("هیچ کالایی تیک نخورده است.")
            return
        try:
            out = self.context.api.read_accessory_pdf(self.data, codes)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.error_label.setText(error_text(exc))
            return
        result = out.get("result") or {}
        widgets.success(self, "لوازم جانبی اضافه شد",
                        f"{format_int(result.get('added') or 0)} کالا اضافه و "
                        f"{format_int(result.get('updated') or 0)} کالا به‌روز شد "
                        f"({format_int(result.get('images') or 0)} عکس).")
        self.accept()
