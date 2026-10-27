"""v2.12.0: the whole «سایت» section end to end against a FAKE GitHub that holds
a copy of the real site's files — never the real repository, no network.

    .venv\\Scripts\\python.exe scripts\\e2e_site_mock.py <site folder> <work folder>

Steps (the real «سایت» page, offscreen; dialogs answered by the script):
 1. «خواندن از سایت» from the fake GitHub
 2. add a phone with a photo per colour, hide another phone
 3. add an accessory with a photo
 4. change the look: colour preset, logo, banner text + picture, hide a section,
    featured phones, brand order, store phone / hours / bot link
 5. «پیش‌نمایش در مرورگر» (base = the fake GitHub's site code)  -> <work>/preview
 6. «انتشار در سایت»                                           -> <work>/published
 7. «برگرداندن انتشار قبلی»                                     -> <work>/rolled_back
 8. backup, change, restore

Each folder is a complete site to open in a browser (``python -m http.server``).
Prints one line per check; exit code 1 when a check fails.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILED: list[str] = []


def check(ok: bool, text: str) -> None:
    print(("OK   " if ok else "FAIL ") + text, flush=True)
    if not ok:
        FAILED.append(text)


def site_files(folder: Path) -> dict[str, bytes]:
    """The committed files of the site clone (what GitHub has)."""
    names = subprocess.run(["git", "-C", str(folder), "ls-files"], capture_output=True,
                           text=True, encoding="utf-8", check=True).stdout.splitlines()
    return {n: (folder / n).read_bytes() for n in names if (folder / n).is_file()}


def write_tree(files: dict[str, bytes], target: Path) -> None:
    import shutil

    if target.exists():
        shutil.rmtree(target)
    for path, data in files.items():
        out = target / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)


def main() -> int:
    site_folder, work = Path(sys.argv[1]), Path(sys.argv[2])
    work.mkdir(parents=True, exist_ok=True)
    import render_screens as rs
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    from app.site import token as tk
    from app.ui import site_dialogs as sd
    from app.ui import site_look as sl
    from app.ui import widgets
    from app.ui.pages import site as site_page
    from app.ui.pages.site import SitePage
    from tests.fake_github import TOKEN, FakeGitHub

    app = QApplication.instance() or QApplication(sys.argv)

    def picture(color: str, w: int = 900, h: int = 700) -> bytes:
        image = QImage(w, h, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        raw = QByteArray()
        buffer = QBuffer(raw)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(raw.data())

    errors: list[str] = []
    widgets.success = lambda *a, **k: None
    widgets.info = lambda *a, **k: None
    widgets.confirm = lambda *a, **k: True
    widgets.error = lambda _p, _t, message, *a, **k: errors.append(message)
    site_page.run_async = lambda task, on_success, on_error, on_done: (on_success(task()),
                                                                        on_done())
    tk._dpapi = lambda data, protect: data            # no Windows key store in this check
    opened: list[str] = []
    SitePage.open_url = staticmethod(opened.append)

    fake = FakeGitHub(files=site_files(site_folder))
    SitePage.github_transport = fake.transport()
    context, _store, _fake_api = rs.build_context(Path(tempfile.mkdtemp(dir=work)))
    tk.save(context.store, TOKEN)
    page = SitePage(context)
    page.load()

    # 1. read from the site
    page._seed_github()
    phones = page.store.items("phone")
    check(len(phones) > 30, f"read from the site: {len(phones)} phones")
    check(not page.store.preview()["has_changes"], "after reading: nothing to publish")

    # 2. add a phone with a photo per colour; hide one
    colors = iter(["#2244aa", "#aa3344"])
    sd.read_photo = lambda _p: picture(next(colors))
    dialog = sd.PhoneDialog(page.store, parent=page)
    dialog.brand.setCurrentIndex(dialog.brand.findData("samsung"))
    dialog.name.setText("Galaxy Test 99")
    for n, name in enumerate(("آبی آزمایشی", "قرمز آزمایشی")):
        dialog._new_color()
        dialog.colors.item(n, 0).setText(name)
        dialog.colors.setCurrentCell(n, 0)
        dialog._color_photo()
    dialog.year.setValue(2027)
    dialog.specs.setPlainText("باتری: 6000 میلی‌آمپر ساعت")
    dialog._save()
    check(page.store.get("galaxy-test-99") is not None, "new phone saved with 2 colour photos")
    hidden = phones[0]
    page.store.set_hidden(hidden["code"], True)

    # 3. an accessory with a photo
    sd.read_photo = lambda _p: picture("#33aa77", 800, 800)
    acc = sd.AccessoryDialog(page.store, parent=page)
    acc.name.setText("شارژر آزمایشی 45W")
    acc._pick_photo()
    acc._save()
    accessory = next((a for a in page.store.items("accessory") if "45W" in a["name"]), None)
    check(accessory is not None and page.store.has_photo(accessory["image"]),
          "accessory saved with its photo")

    # 4. the look
    look = page.look_tab
    look.palette_cards["sunset"].click()
    sl.read_picture = lambda _p: picture("#ff8800", 300, 300)
    look._pick_logo()
    sl.read_picture = lambda _p: picture("#116688", 1600, 800)
    look._add_banner()
    look.hero_inputs["title"].setText("گوشی آزمایشی")
    look.hero_inputs["highlight"].setText("با ظاهر تازه.")
    look._dirty("banner")
    rows = page.store.look()["sections"]
    look.sections.list.item([s["key"] for s in rows].index("faq")).setCheckState(
        Qt.CheckState.Unchecked)
    page.store.update_look(lambda v: v.update(featured=["galaxy-test-99", phones[1]["code"]]))
    look.brand_order.list.setCurrentRow(2)
    look.brand_order.step(-2)
    look.store_inputs["phone"].setText("05131234567")
    look.store_inputs["telegram_channel"].setText("@asr_test_channel")
    look.hour_inputs[0][0].setText("هر روز")
    look.hour_inputs[0][1].setText("۱۰ تا ۲۲")
    look._dirty("store")
    preview = page.store.preview()
    lines = "\n".join(preview["lines"])

    # 5. browser preview (unsaved forms are saved first)
    page._preview_browser()
    check(bool(opened) and opened[-1].startswith("http://127.0.0.1:"), "preview opened on 127.0.0.1")
    check(page.store.look()["hero"]["title"] == "گوشی آزمایشی", "unsaved banner text saved first")
    preview_dir = page.store.root / "preview"
    site = json.loads((preview_dir / "assets/catalog/site.json").read_text("utf-8"))
    check(site["palette"] == "sunset" and site["store"]["phone"] == "05131234567",
          "preview has the new look")
    print("PREVIEW_URL", opened[-1], flush=True)
    lines = "\n".join(page.store.preview()["lines"])
    for word in ("Galaxy Test 99", "شارژر آزمایشی", "نارنجی غروب", "لوگو", "بنر",
                 "پنهان: سؤالات پرتکرار", "ترتیب برندها", "اطلاعات فروشگاه"):
        check(word in lines, f"preview text says: {word}")

    # 6. publish
    before_files = fake.files()
    page._publish()
    files = fake.files()
    catalog = json.loads(files["assets/catalog/catalog.json"])
    site = json.loads(files["assets/catalog/site.json"])
    codes = [i["code"] for i in catalog["items"]]
    check("galaxy-test-99" in codes and hidden["code"] not in codes, "published: new phone in, hidden out")
    check(any(i["category"] == "accessory" and "45W" in i["name"] for i in catalog["items"]),
          "published: accessory in")
    check(site["palette"] == "sunset" and site.get("logo", "").startswith("look/logo-"),
          "published: look")
    check(all("assets/catalog/" + p in files for p in site["images"]), "published: every look picture is in the repo")
    check(fake.dispatches == ["main"], "deploy started once")
    check(not page.store.preview()["has_changes"], "after publishing: nothing left")
    check(all(files[p] == before_files[p] for p in before_files if not p.startswith("assets/catalog/")),
          "publish touched only assets/catalog/")
    write_tree(files, work / "published")

    # 7. roll back
    page._rollback()
    files = fake.files()
    check("assets/catalog/site.json" not in files and "assets/catalog/catalog.json" not in files,
          "rolled back: the site is as before (no catalogue / look files)")
    check(files == before_files, "rolled back: every file exactly as before the publish")
    write_tree(files, work / "rolled_back")

    # 8. backup / restore
    backup = work / "site-backup.zip"
    page.store.backup(backup)
    page.store.update_look(lambda v: v.update(palette="violet", logo=""))
    page.store.set_hidden("galaxy-test-99", True)
    page.store.restore(backup)
    page.load()
    check(page.store.look()["palette"] == "sunset" and page.store.look()["logo"]
          and not page.store.get("galaxy-test-99")["hidden"], "backup / restore: look and phones back")
    check(look.palette_cards["sunset"].isChecked(), "restored look shown in the tab")
    check(not errors, f"no error dialogs ({errors[:2]})")
    check(TOKEN not in json.dumps({k: v.decode("utf-8", "replace")
                                   for k, v in fake.files().items()}), "token never in the repo")
    print(f"{len(FAILED)} failed", flush=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
