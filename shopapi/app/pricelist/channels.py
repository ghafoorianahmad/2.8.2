"""v2.14.0: price lists of OTHER Telegram channels (role «کانال قیمت دیگر»).

* The main list (Abrishami, role ``pricelist``) stays the bot's price basis,
  automatically, as before; nothing here waits for the owner.
* Every file / post of another price channel (PDF, picture, Excel, plain text)
  is read and stored with the channel's name («لیست‌های دریافتی»). It is never
  compared with the main list.
* A row that is not sure (``state != ok``) is never used, only shown; a picture
  list keeps every row's box, so ShopAdmin shows the cropped row next to what
  was read.
* The owner may make one such list (and one of its price columns: low / high)
  the basis **for a while** - until a time or the end of today (Tehran); then
  the main list is the basis again by itself. A picture list can be the basis
  only after the owner approved it. While another list is the basis, its rows
  can only be *requested* in the bot (they are not mapped to «سازه حساب»), so
  staff always confirm the price.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from ..config import Settings
from ..db_own import OwnDB
from ..util import now_iso, now_utc
from . import image_reader
from .pdf_archive import TEHRAN

logger = logging.getLogger("shopapi.pricelist")

BASIS_KEY = "pricelist:basis_override"
EVENT_STORED = "channel_list_stored"
EVENT_BASIS = "price_basis_changed"
KINDS = ("pdf", "image", "excel", "text")
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 2000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL DEFAULT '',
    channel_title TEXT NOT NULL DEFAULT '',
    source_ref TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    file_name TEXT,
    posted_at TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,           -- read | failed
    reason TEXT NOT NULL DEFAULT '',
    rows_json TEXT NOT NULL DEFAULT '[]',
    total INTEGER NOT NULL DEFAULT 0,
    usable INTEGER NOT NULL DEFAULT 0,
    approved_at TEXT,
    approved_by TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS channel_lists_sha ON channel_lists (channel, sha256);
"""


def _ensure(db: OwnDB) -> None:
    with db._lock:
        db._conn.executescript(_SCHEMA)
        db._commit()


def kind_of(data: bytes, text: str = "") -> str:
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"\x89PNG") or data[:3] == b"\xff\xd8\xff":
        return "image"
    if data.startswith(b"PK") and b"xl/" in data[:4000]:
        return "excel"
    return "text" if (text or "").strip() else ""


# ---- reading ------------------------------------------------------------------------------
_TEXT_ROW = re.compile(r"^(?P<name>.*?[A-Za-z؀-ۿ].*?)\s+(?P<p1>\d{1,3}(?:[,٬]\d{3})+|\d{4,8})"
                       r"(?:\s*[-–]\s*(?P<p2>\d{1,8}(?:[,٬]\d{3})*))?\s*$")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _text_rows(lines) -> list[dict]:
    rows = []
    for raw in lines:
        line = " ".join(str(raw or "").translate(_DIGITS).split())
        if not line:
            continue
        match = _TEXT_ROW.match(line)
        if not match:
            continue
        low = int(re.sub(r"\D", "", match.group("p1")))
        high = match.group("p2")
        if high:
            parsed = image_reader.parse_range(f"{low}-{re.sub(r'[^0-9]', '', high)}")
            low, high_value = parsed if parsed else (low, low)
        else:
            high_value = low
        name = match.group("name").strip(" -:|")
        row = {"brand": "", "name": name, "color": "", "price_min": low,
               "price_max": high_value, "state": "ok", "reasons": [], "box": [0, 0, 0, 0]}
        if high_value < low or not image_reader.MIN_PRICE <= low <= image_reader.MAX_PRICE:
            row["state"], row["reasons"] = "doubtful", ["قیمت نامعمول"]
        rows.append(row)
    return rows[:MAX_ROWS]


def read_file(kind: str, data: bytes, text: str, folder: Path | None) -> tuple[list[dict], str]:
    """(rows, reason) — reason is set when the file could not be read at all."""
    if kind == "text":
        return _text_rows(text.splitlines()), ""
    if kind == "pdf":
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(data)) as pdf:
                lines = [line for page in pdf.pages[:40]
                         for line in (page.extract_text() or "").splitlines()]
        except Exception:  # noqa: BLE001 - pdfminer raises many kinds
            return [], "PDF خوانده نشد"
        return _text_rows(lines), ""
    if kind == "excel":
        try:
            import openpyxl
        except ImportError:
            return [], "خوانندهٔ Excel روی سرور نیست"
        try:
            book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            lines = [" ".join(str(c) for c in row if c not in (None, ""))
                     for sheet in book.worksheets for row in sheet.iter_rows(values_only=True)]
        except Exception:  # noqa: BLE001
            return [], "فایل Excel خوانده نشد"
        return _text_rows(lines), ""
    if kind == "image":
        if folder is None:
            return [], "پوشهٔ بایگانی نیست"
        path = folder / f"tmp-{hashlib.sha256(data).hexdigest()[:16]}"
        try:
            path.write_bytes(data)
            rows = [r.public() for r in image_reader.read_image(path)]
        except image_reader.OcrUnavailable as exc:
            return [], f"خواندن عکس روی این رایانه ممکن نیست ({exc})"
        except OSError:
            return [], "عکس ذخیره نشد"
        finally:
            path.unlink(missing_ok=True)
        return rows[:MAX_ROWS], ""
    return [], "نوع فایل شناخته نشد"


def _folder(settings: Settings) -> Path | None:
    base = settings.pricelists_path()
    return None if base is None else base / "channels"


def store(db: OwnDB, settings: Settings, *, channel: str, channel_title: str, data: bytes,
          text: str = "", source_ref: str = "", posted_at: str | None = None,
          file_name: str = "") -> dict:
    """Read and keep one post of another price channel. The same file of the same
    channel is kept once (``duplicate``)."""
    _ensure(db)
    if len(data) > MAX_BYTES:
        return {"outcome": "too_large"}
    kind = kind_of(data, text)
    if not kind:
        return {"outcome": "ignored"}
    body = data if data else text.encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()
    with db._lock:
        found = db._conn.execute("SELECT id FROM channel_lists WHERE channel=? AND sha256=?",
                                 (channel, sha)).fetchone()
    if found:
        return {"outcome": "duplicate", "id": int(found[0])}
    folder = _folder(settings)
    stored_name = None
    if folder is not None and data:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            ext = {"pdf": ".pdf", "image": ".png" if data.startswith(b"\x89PNG") else ".jpg",
                   "excel": ".xlsx"}.get(kind, ".bin")
            stored_name = f"{sha[:20]}{ext}"
            (folder / stored_name).write_bytes(data)
        except OSError as exc:
            logger.warning("channel file not kept: %s", type(exc).__name__)
            stored_name = None
    rows, reason = read_file(kind, data, text, folder)
    usable = sum(1 for r in rows if r.get("state") == "ok")
    status = "read" if rows else "failed"
    with db._lock:
        cur = db._conn.execute(
            "INSERT INTO channel_lists (channel, channel_title, source_ref, kind, sha256, "
            "file_name, posted_at, created_at, status, reason, rows_json, total, usable) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (channel, channel_title[:120], source_ref[:200], kind, sha, stored_name, posted_at,
             now_iso(), status, reason or ("" if rows else "ردیفی خوانده نشد"),
             json.dumps(rows, ensure_ascii=False), len(rows), usable))
        db._commit()
        list_id = int(cur.lastrowid)
    db.add_event(EVENT_STORED, list_id, "worker")
    return {"outcome": status, "id": list_id, "rows": len(rows), "usable": usable}


def _out(row) -> dict:
    keys = ("id", "channel", "channel_title", "source_ref", "kind", "file_name", "posted_at",
            "created_at", "status", "reason", "total", "usable", "approved_at", "approved_by")
    return dict(zip(keys, row))


def lists(db: OwnDB, limit: int = 100) -> list[dict]:
    _ensure(db)
    with db._lock:
        rows = db._conn.execute(
            "SELECT id, channel, channel_title, source_ref, kind, file_name, posted_at, "
            "created_at, status, reason, total, usable, approved_at, approved_by "
            "FROM channel_lists ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    basis = basis_state(db)
    out = []
    for row in rows:
        item = _out(row)
        item["is_basis"] = bool(basis and basis.get("list_id") == item["id"])
        out.append(item)
    return out


def get(db: OwnDB, list_id: int) -> dict | None:
    _ensure(db)
    with db._lock:
        row = db._conn.execute(
            "SELECT id, channel, channel_title, source_ref, kind, file_name, posted_at, "
            "created_at, status, reason, total, usable, approved_at, approved_by, rows_json "
            "FROM channel_lists WHERE id=?", (int(list_id),)).fetchone()
    if row is None:
        return None
    item = _out(row[:-1])
    item["rows"] = json.loads(row[-1] or "[]")
    return item


def crop(db: OwnDB, settings: Settings, list_id: int, index: int) -> bytes | None:
    """The PNG of one row of a picture list (for the preview)."""
    item = get(db, list_id)
    folder = _folder(settings)
    if not item or item["kind"] != "image" or not item.get("file_name") or folder is None:
        return None
    if not 0 <= index < len(item["rows"]):
        return None
    from PIL import Image

    x, y, w, h = item["rows"][index].get("box") or (0, 0, 0, 0)
    try:
        picture = Image.open(folder / Path(item["file_name"]).name)
        part = picture.crop((max(0, x - 6), max(0, y - 4), x + w + 6, y + h + 4))
        buffer = io.BytesIO()
        part.convert("RGB").save(buffer, "PNG")
        return buffer.getvalue()
    except OSError:
        return None


def approve(db: OwnDB, list_id: int, actor: str) -> dict | None:
    _ensure(db)
    with db._lock:
        db._conn.execute("UPDATE channel_lists SET approved_at=?, approved_by=? WHERE id=?",
                         (now_iso(), actor, int(list_id)))
        db._commit()
    db.audit(actor, "channel_list_approve", f"list id={list_id}")
    return get(db, list_id)


# ---- the temporary basis ---------------------------------------------------------------------
def end_of_today(now: datetime | None = None) -> datetime:
    local = (now or now_utc()).astimezone(TEHRAN)
    end = local.replace(hour=23, minute=59, second=59, microsecond=0)
    return end.astimezone(now_utc().tzinfo)


def basis_state(db: OwnDB, now: datetime | None = None) -> dict | None:
    """The other list that is the basis now, or None (= the main list). An
    expired choice is cleared here (the main list is the basis again)."""
    try:
        value = json.loads(db.get_state(BASIS_KEY, "") or "null")
    except ValueError:
        value = None
    if not isinstance(value, dict):
        return None
    try:
        until = datetime.fromisoformat(str(value.get("until")))
    except ValueError:
        until = None
    if until is None or (now or now_utc()) >= until:
        db.set_state(BASIS_KEY, "", "system")
        db.add_event(EVENT_BASIS, value.get("list_id"), "system")
        return None
    return value


def set_basis(db: OwnDB, list_id: int, column: str, until: datetime, actor: str) -> dict:
    """Raises ValueError (English detail, ShopAdmin translates) when not allowed."""
    item = get(db, list_id)
    if item is None:
        raise ValueError("unknown channel list")
    if item["status"] != "read" or not item["usable"]:
        raise ValueError("channel list has no usable rows")
    if item["kind"] == "image" and not item.get("approved_at"):
        raise ValueError("picture list not approved")
    if column not in ("min", "max"):
        raise ValueError("unknown price column")
    if until <= now_utc() or until > now_utc() + timedelta(days=7):
        raise ValueError("basis time out of range")
    value = {"list_id": int(list_id), "column": column, "until": until.isoformat(),
             "by": actor, "at": now_iso()}
    db.set_state(BASIS_KEY, json.dumps(value), actor)
    db.audit(actor, "price_basis_set", f"list id={list_id} column={column} until={value['until']}")
    db.add_event(EVENT_BASIS, int(list_id), actor)
    return value


def clear_basis(db: OwnDB, actor: str) -> None:
    db.set_state(BASIS_KEY, "", actor)
    db.audit(actor, "price_basis_clear", "main list")
    db.add_event(EVENT_BASIS, None, actor)


def basis_rows(db: OwnDB, settings: Settings) -> tuple[dict, list[dict]] | None:
    """While another list is the basis: (a list-like dict, rows in the shape of the
    main list's rows; never mapped -> only «درخواست خرید» in the bot)."""
    basis = basis_state(db)
    if not basis:
        return None
    item = get(db, int(basis["list_id"]))
    if item is None:
        return None
    unit = int(settings.pricelist_unit_rial or 1)
    rows = []
    for n, row in enumerate(item["rows"]):
        if row.get("state") != "ok":
            continue                     # a doubtful row is never used
        price = row.get("price_max") if basis["column"] == "max" else row.get("price_min")
        if not price:
            continue
        rows.append({"row_key": f"ch{item['id']}-{n}", "block": "", "section": row.get("brand") or "",
                     "description": row.get("name") or "", "kind": "", "color": row.get("color") or "",
                     "price_rial": int(price) * unit, "price_flag": "", "flag_note": "",
                     "mapping_id": None, "action": None, "kala_code": None, "color_label": "",
                     "auto": 0, "auto_reason": "", "pending_price_rial": None})
    listed = {"id": None, "list_date": (item.get("posted_at") or item["created_at"])[:10],
              "channel": item.get("channel_title") or item.get("channel"), "basis": basis}
    return listed, rows
