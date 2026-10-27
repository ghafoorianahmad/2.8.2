"""v2.11.0: the site's data on THIS computer only (ShopAdmin's data folder):

    <data>/site/site_data.json   brands + items (phones and accessories)
    <data>/site/photos/          photos in the site standard (1280×1024 JPEG)
    <data>/site/published.json   what the site shows now (the preview compares with it)
    <data>/site/history/         one record per publish, for «برگرداندن انتشار قبلی»
                                 (48 hours, then deleted automatically)

Nothing of it is sent to the shop server. A backup is one zip of the three
first parts; a restore first keeps a copy of the current data.
"""
from __future__ import annotations

import json
import os
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from . import catalog as cat
from . import photos as ph

ROLLBACK_HOURS = 48
BACKUP_MARK = "shopadmin-site-backup"


class SiteDataError(ValueError):
    """Something the user can fix (Persian reason)."""


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class SiteStore:
    def __init__(self, root: Path | str, *, clock: Callable[[], datetime] | None = None):
        self.root = Path(root)
        self.photos_dir = self.root / "photos"
        self.history_dir = self.root / "history"
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ---- working data ------------------------------------------------------------------
    @property
    def data_path(self) -> Path:
        return self.root / "site_data.json"

    def load(self) -> dict:
        data = _json(self.data_path, None)
        if not isinstance(data, dict) or data.get("format") != cat.DATA_FORMAT:
            return {"format": cat.DATA_FORMAT, "version": 1, "brands": list(cat.DEFAULT_BRANDS),
                    "items": [], "seeded": ""}
        data["items"] = [cat.clean_item(i) for i in data.get("items") or []]
        return data

    def save(self, data: dict) -> None:
        data = dict(data)
        data["format"], data["version"], data["updated_at"] = cat.DATA_FORMAT, 1, cat.now_iso()
        _write_atomic(self.data_path, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))

    def is_empty(self) -> bool:
        return not self.load()["items"]

    def items(self, category: str | None = None) -> list[dict]:
        rows = self.load()["items"]
        return [i for i in rows if category is None or i["category"] == category]

    def brand_keys(self) -> set[str]:
        return {b["key"] for b in self.load()["brands"]}

    def get(self, code: str) -> Optional[dict]:
        return next((i for i in self.items() if i["code"] == code), None)

    def upsert(self, item: dict, *, old_code: str = "") -> dict:
        """Add or replace an item. Raises SiteDataError (Persian) when invalid."""
        data = self.load()
        clean = cat.clean_item(item)
        problems = cat.item_problems(clean, {b["key"] for b in data["brands"]})
        codes = {i["code"] for i in data["items"]} - {old_code or clean["code"]}
        if clean["code"] in codes:
            problems.append("این کد مدل برای کالای دیگری است.")
        if problems:
            raise SiteDataError(" ".join(problems))
        replaced = False
        for n, row in enumerate(data["items"]):
            if row["code"] == (old_code or clean["code"]):
                data["items"][n] = clean
                replaced = True
                break
        if not replaced:
            data["items"].append(clean)
        self.save(data)
        return clean

    def set_hidden(self, code: str, hidden: bool) -> None:
        data = self.load()
        for row in data["items"]:
            if row["code"] == code:
                row["hidden"] = bool(hidden)
        self.save(data)

    # ---- photos ------------------------------------------------------------------------
    def photo_hashes(self) -> dict[str, str]:
        if not self.photos_dir.is_dir():
            return {}
        return {p.name: cat.sha256(p.read_bytes()) for p in sorted(self.photos_dir.iterdir())
                if p.is_file() and cat.IMAGE_NAME_RE.match(p.name)}

    def has_photo(self, name: str) -> bool:
        return bool(name) and (self.photos_dir / name).is_file()

    def photo_path(self, name: str) -> Path:
        return self.photos_dir / name

    def add_photo(self, name: str, data: bytes) -> list[str]:
        """Store a photo in the site standard; returns Persian notes."""
        if not cat.IMAGE_NAME_RE.match(name or ""):
            raise SiteDataError("نام فایل عکس نادرست است.")
        jpeg, notes = ph.normalize(data)
        _write_atomic(self.photos_dir / name, jpeg)
        return notes

    # ---- seed from the site's own files --------------------------------------------------
    def seed(self, products_js: str, site_js: str,
             fetch_photo: Callable[[str], Optional[bytes]], *, source: str) -> dict:
        """Read the site's catalogue (models, colours, specs) and its photos. Items
        already here are kept; only new codes are added."""
        try:
            parsed = cat.parse_site_files(products_js, site_js)
        except cat.JsLiteralError:
            raise SiteDataError("فایل products.js سایت خوانده نشد.") from None
        return self._seed(parsed, fetch_photo, source=source)

    def seed_from_catalog(self, catalog_json: bytes,
                          fetch_photo: Callable[[str], Optional[bytes]], *, source: str) -> dict:
        """The same from a published catalog.json (the site already uses one)."""
        try:
            parsed = cat.items_from_catalog(json.loads(catalog_json.decode("utf-8")))
        except (ValueError, cat.JsLiteralError):
            raise SiteDataError("فایل catalog.json سایت خوانده نشد.") from None
        return self._seed(parsed, fetch_photo, source=source)

    def _seed(self, parsed: dict, fetch_photo: Callable[[str], Optional[bytes]], *,
              source: str) -> dict:
        if not parsed["items"]:
            raise SiteDataError("در فایل سایت مدلی پیدا نشد.")
        data = self.load()
        have = {i["code"] for i in data["items"]}
        added = [i for i in parsed["items"] if i["code"] not in have]
        data["items"].extend(added)
        if parsed["brands"]:
            data["brands"] = parsed["brands"]
        data["seeded"] = source
        photos = missing = 0
        for item in added:
            for name in cat.image_refs(item):
                if self.has_photo(name):
                    continue
                raw = fetch_photo(name)
                if raw is None:
                    missing += 1
                    continue
                try:
                    self.add_photo(name, raw)
                    photos += 1
                except (ph.PhotoError, SiteDataError):
                    missing += 1
        self.save(data)
        if not (self.root / "published.json").is_file():
            # the site as it is now: the first preview shows only real changes
            self.mark_published(self.build()[0], commit="", note="site as read")
        return {"models": len(parsed["items"]), "added": len(added), "photos": photos,
                "missing_photos": missing}

    def seed_from_folder(self, folder: Path | str) -> dict:
        root = Path(folder)
        products = root / "assets" / "products.js"
        if not products.is_file():
            raise SiteDataError("در این پوشه assets/products.js نیست؛ پوشهٔ اصلی سایت را "
                                "انتخاب کنید.")
        site = root / "assets" / "site.js"

        def fetch(name: str) -> Optional[bytes]:
            for path in (root / "assets" / "products" / name,
                         root / cat.SITE_CATALOG_DIR / "images" / name):
                if path.is_file():
                    return path.read_bytes()
            return None

        return self.seed(products.read_text(encoding="utf-8"),
                         site.read_text(encoding="utf-8") if site.is_file() else "",
                         fetch, source=str(root))

    # ---- catalog.json + preview --------------------------------------------------------
    def build(self, generator: str = "ShopAdmin") -> tuple[dict, dict[str, Path]]:
        """(catalog.json, {path in the site repository: photo file})."""
        hashes = self.photo_hashes()
        catalog = cat.build_catalog(self.load(), hashes, generator=generator)
        files = {f"{cat.SITE_CATALOG_DIR}/{path}": self.photos_dir / path[len(cat.IMAGES_PREFIX):]
                 for path in catalog["images"]}
        return catalog, files

    def published(self) -> Optional[dict]:
        value = _json(self.root / "published.json", None)
        return value if isinstance(value, dict) else None

    def preview(self) -> dict:
        catalog, _files = self.build()
        old = (self.published() or {}).get("snapshot")
        change = cat.diff(old, cat.snapshot(catalog))
        return {"change": change, "lines": cat.preview_lines(change),
                "has_changes": cat.has_changes(change),
                "problems": cat.validate_catalog(catalog),
                "phones": sum(1 for i in catalog["items"] if i["category"] == cat.KIND_PHONE),
                "accessories": sum(1 for i in catalog["items"]
                                   if i["category"] == cat.KIND_ACCESSORY),
                "images": len(catalog["images"]),
                "last": self.published()}

    def mark_published(self, catalog: dict, *, commit: str, note: str = "") -> None:
        record = {"at": self.clock().isoformat(timespec="seconds"), "commit": commit,
                  "note": note, "snapshot": cat.snapshot(catalog)}
        _write_atomic(self.root / "published.json",
                      json.dumps(record, ensure_ascii=False).encode("utf-8"))

    # ---- publish history (48 hours) ----------------------------------------------------
    def add_history(self, record: dict) -> Path:
        """One publish: {commit, previous: {path: blob sha or None}, snapshot_before}."""
        self.purge_history()
        stamp = self.clock().strftime("%Y%m%d%H%M%S")
        n = 1
        path = self.history_dir / f"publish-{stamp}-{n:03d}.json"
        while path.exists():          # two publishes in the same second
            n += 1
            path = self.history_dir / f"publish-{stamp}-{n:03d}.json"
        record = {**record, "at": self.clock().isoformat(timespec="seconds")}
        _write_atomic(path, json.dumps(record, ensure_ascii=False).encode("utf-8"))
        return path

    def purge_history(self) -> int:
        """Delete publish records older than 48 hours. Returns how many."""
        if not self.history_dir.is_dir():
            return 0
        limit = self.clock() - timedelta(hours=ROLLBACK_HOURS)
        removed = 0
        for path in self.history_dir.glob("publish-*.json"):
            record = _json(path, {})
            try:
                when = datetime.fromisoformat(str(record.get("at")))
            except ValueError:
                when = limit - timedelta(seconds=1)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when < limit or record.get("rolled_back"):
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    def last_rollback(self) -> Optional[tuple[Path, dict]]:
        """The newest publish that can still be undone (within 48 hours)."""
        self.purge_history()
        if not self.history_dir.is_dir():
            return None
        records = sorted(self.history_dir.glob("publish-*.json"))
        for path in reversed(records):
            record = _json(path, {})
            if record.get("commit") and not record.get("rolled_back"):
                return path, record
        return None

    def rollback_deadline(self, record: dict) -> Optional[datetime]:
        try:
            when = datetime.fromisoformat(str(record.get("at")))
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when + timedelta(hours=ROLLBACK_HOURS)

    def finish_rollback(self, path: Path, record: dict, commit: str) -> None:
        """After a rollback commit: the site shows the state before that publish."""
        before = record.get("snapshot_before")
        if isinstance(before, dict):
            _write_atomic(self.root / "published.json", json.dumps(
                {"at": self.clock().isoformat(timespec="seconds"), "commit": commit,
                 "note": "rollback", "snapshot": before}, ensure_ascii=False).encode("utf-8"))
        path.unlink(missing_ok=True)

    # ---- backup / restore --------------------------------------------------------------
    def backup(self, target: Path | str) -> int:
        """One zip with the data, the photos and the published state."""
        target = Path(target)
        count = 0
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("BACKUP.txt", f"{BACKUP_MARK} {cat.now_iso()}\n")
            for name in ("site_data.json", "published.json"):
                if (self.root / name).is_file():
                    archive.write(self.root / name, name)
            for name in self.photo_hashes():
                archive.write(self.photos_dir / name, f"photos/{name}",
                              compress_type=zipfile.ZIP_STORED)
                count += 1
        return count

    def restore(self, source: Path | str) -> dict:
        """Replace the data with a backup. The current data is kept first as
        ``site_before_restore_<time>`` next to it. Raises SiteDataError."""
        try:
            archive = zipfile.ZipFile(Path(source))
        except (OSError, zipfile.BadZipFile):
            raise SiteDataError("این فایل پشتیبان سالم نیست.") from None
        with archive:
            names = archive.namelist()
            if "BACKUP.txt" not in names or not archive.read("BACKUP.txt").decode(
                    "utf-8", "replace").startswith(BACKUP_MARK) or "site_data.json" not in names:
                raise SiteDataError("این فایل پشتیبانِ بخش «سایت» نیست.")
            data = json.loads(archive.read("site_data.json").decode("utf-8"))
            if not isinstance(data, dict) or data.get("format") != cat.DATA_FORMAT:
                raise SiteDataError("این فایل پشتیبانِ بخش «سایت» نیست.")
            photos = [n for n in names if n.startswith("photos/")
                      and cat.IMAGE_NAME_RE.match(n[len("photos/"):])]
            if self.root.is_dir():
                keep = self.root.parent / f"site_before_restore_{self.clock():%Y%m%d%H%M%S}"
                shutil.copytree(self.root, keep, ignore=shutil.ignore_patterns("history"))
            if self.photos_dir.is_dir():
                shutil.rmtree(self.photos_dir)
            for name in photos:
                _write_atomic(self.photos_dir / name[len("photos/"):], archive.read(name))
            _write_atomic(self.data_path, archive.read("site_data.json"))
            if "published.json" in names:
                _write_atomic(self.root / "published.json", archive.read("published.json"))
        return {"items": len(data.get("items") or []), "photos": len(photos)}
