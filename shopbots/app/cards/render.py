"""Light "invoice sheet" cards: HTML/CSS templates screenshotted by a headless browser.

Design (see docs/card-samples/invoice-reference.jpg): white / very light blue page with
soft blue waves at the top and bottom, shop header + phone/store illustration, rounded
info boxes with icons, a table with a dark-blue header row, a dark-blue totals panel with
large bold numbers, a notes box, and a footer with the date and a signature line.

* Font: Vazirmatn (OFL, ``assets/``) embedded in the page as base64 - no system fonts.
* Icons: Tabler Icons (MIT, subset in ``assets/icons.json``) inlined as SVG.
* Browser: no download and no Playwright. A Chromium-family binary is run with
  ``--headless --screenshot``: Microsoft Edge on the Windows server (always installed),
  Chrome/Chromium elsewhere. ``BOT_CARD_BROWSER`` overrides the path.
* Persian shaping and RTL are the browser's job (no reshaper / bidi libraries).

Every public function returns PNG bytes, or ``None`` when anything fails (no browser,
timeout, bad output): the caller then sends the plain text message instead.
"""
from __future__ import annotations

import base64
import functools
import html
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .jdate import shamsi_date
from .numwords import amount_in_words

logger = logging.getLogger("shopbots.cards")

ASSETS = Path(__file__).resolve().parent / "assets"
FONT_REGULAR = ASSETS / "Vazirmatn-Regular.ttf"
FONT_BOLD = ASSETS / "Vazirmatn-Bold.ttf"
ICONS_FILE = ASSETS / "icons.json"
LOGO_FILE = ASSETS / "logo.png"       # shop logo (transparent PNG)

W = 1080
WINDOW_PAD = 200            # extra window height; the image is cropped to the page
RENDER_TIMEOUT = 40          # seconds for one screenshot

_FA_DIGITS = str.maketrans("0123456789,.", "۰۱۲۳۴۵۶۷۸۹٬٫")


def fa_num(value) -> str:
    """12345678 -> ۱۲٬۳۴۵٬۶۷۸ (display digits)."""
    try:
        return f"{float(value):,.0f}".translate(_FA_DIGITS)
    except (TypeError, ValueError):
        return "۰"


def fa_digits(text) -> str:
    return str(text).translate(_FA_DIGITS)


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


# ------------------------------------------------------------------- browser
_WIN_BROWSERS = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
)
_PATH_BROWSERS = ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser", "chrome")


@functools.lru_cache(maxsize=1)
def find_browser() -> str | None:
    """Path of a Chromium-family browser, or None (cards then fall back to text)."""
    override = os.environ.get("BOT_CARD_BROWSER", "").strip()
    if override:
        return override if Path(override).exists() else None
    if sys.platform == "win32":
        for raw in _WIN_BROWSERS:
            p = Path(os.path.expandvars(raw))
            if p.exists():
                return str(p)
    for name in _PATH_BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    pw = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for p in sorted(pw.glob("chromium-*/chrome-linux*/chrome")):
        return str(p)
    return None


def _screenshot(page_html: str, height: int) -> bytes | None:
    browser = find_browser()
    if not browser:
        logger.warning("cards: no Chromium/Edge found (set BOT_CARD_BROWSER) - text fallback")
        return None
    with tempfile.TemporaryDirectory(prefix="shopcard_") as tmp:
        tmpd = Path(tmp)
        page = tmpd / "card.html"
        out = tmpd / "card.png"
        page.write_text(page_html, encoding="utf-8")
        cmd = [
            browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
            "--no-first-run", "--disable-extensions", "--disable-background-networking",
            "--force-device-scale-factor=1", f"--window-size={W},{height + WINDOW_PAD}",
            "--virtual-time-budget=3000", f"--user-data-dir={tmpd / 'profile'}",
            f"--screenshot={out}", page.as_uri(),
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(cmd, check=False, timeout=RENDER_TIMEOUT, creationflags=flags,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            logger.warning("cards: browser timed out - text fallback")
            return None
        if not out.exists():
            logger.warning("cards: browser produced no image - text fallback")
            return None
        data = out.read_bytes()
    return _crop(data, height)


def _crop(png: bytes, height: int) -> bytes | None:
    """Keep exactly W x height: a headless window is a few dozen px shorter than asked
    for its viewport, so the page is rendered into a taller window and cropped here."""
    if not png.startswith(b"\x89PNG"):
        return None
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGB")
    if img.width != W or img.height < height:
        return None
    out = io.BytesIO()
    img.crop((0, 0, W, height)).save(out, format="PNG", optimize=True)
    return out.getvalue()


# --------------------------------------------------------------------- assets
@functools.lru_cache(maxsize=1)
def _icons() -> dict:
    return json.loads(ICONS_FILE.read_text(encoding="utf-8"))


def icon(name: str, size: int = 28, cls: str = "") -> str:
    inner = _icons().get(name) or _icons()["tag"]
    return (f'<svg class="ic {cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{inner}</svg>')


@functools.lru_cache(maxsize=2)
def _font_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _item_icon(name: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in ("کاور", "قاب", "گلس", "محافظ", "case", "cover", "glass")):
        return "shield-check"
    if any(k in n for k in ("شارژ", "باتری", "پاوربانک", "charger", "power", "cable", "کابل")):
        return "bolt"
    if any(k in n for k in ("هندزفری", "هدفون", "ایرپاد", "airpod", "buds", "headphone")):
        return "headphones"
    return "device-mobile"


# ------------------------------------------------------------------------- CSS
_CSS = """
:root{--navy:#0b3d86;--navy2:#0a2f6b;--blue:#1d6fd6;--line:#9cc3ee;--soft:#eaf3fd;--ink:#0d2a55;--mute:#4f6a8f;--good:#0f9d6b;--bad:#d64545}
*{box-sizing:border-box;margin:0;padding:0}
html{background:#f1f7ff}html,body{width:1080px;height:__H__px;overflow:hidden}
body{font-family:'Vazirmatn',sans-serif;direction:rtl;color:var(--ink);background:linear-gradient(180deg,#ffffff 0%,#f1f7ff 100%);position:relative;font-size:26px;line-height:1.5}
@font-face{font-family:'Vazirmatn';font-weight:400;src:url(data:font/ttf;base64,__FR__) format('truetype')}
@font-face{font-family:'Vazirmatn';font-weight:700;src:url(data:font/ttf;base64,__FB__) format('truetype')}
.wave{position:absolute;left:0;width:1080px;pointer-events:none}
.wave.top{top:0;height:170px}.wave.bot{bottom:0;height:150px}
.page{position:relative;padding:34px 44px 0;z-index:1}
.head{display:flex;align-items:center;justify-content:space-between;gap:20px;height:210px}
.brand{flex:1;text-align:center}
.brand .t{font-size:46px;font-weight:700;color:var(--navy);line-height:1.3}
.brand .s{font-size:25px;color:var(--mute);margin-top:6px;display:flex;align-items:center;justify-content:center;gap:12px}
.brand .s:before,.brand .s:after{content:"";height:2px;width:46px;background:var(--line)}
.illus{width:260px;height:190px;flex:none}
.metabox{width:340px;flex:none;border:2px solid var(--line);border-radius:22px;background:rgba(234,243,253,.85);padding:12px 20px;display:flex;flex-direction:column;gap:6px}
.meta{display:flex;align-items:center;gap:10px;font-size:23px;white-space:nowrap}
.meta .ic{color:var(--navy);flex:none}.meta b{color:var(--navy)}.meta .v{margin-inline-start:auto;font-weight:700}
.sep{height:2px;background:linear-gradient(90deg,transparent,var(--line),transparent);margin:14px 0 18px}
.boxes{display:flex;gap:18px;margin-bottom:20px}
.box{flex:1;border:2px solid var(--line);border-radius:22px;background:var(--soft);padding:16px 22px;min-width:0}
.box h3{font-size:28px;color:var(--navy);display:flex;align-items:center;gap:10px;margin-bottom:6px}
.box p{font-size:24px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.box p b{color:var(--mute);font-weight:400}
table{width:100%;border-collapse:separate;border-spacing:0;border:2px solid var(--navy);border-radius:20px;overflow:hidden;background:#fff;table-layout:fixed}
th{background:var(--navy);color:#fff;font-size:24px;font-weight:700;height:68px;padding:0 12px;border-inline-start:1px solid rgba(255,255,255,.28)}
th:first-child{border-inline-start:0}
th .in{display:inline-flex;align-items:center;gap:10px}
td{height:__ROW__px;padding:0 14px;border-top:1px solid #c8dcf4;font-size:25px;border-inline-start:1px solid #c8dcf4;overflow:hidden}
td:first-child{border-inline-start:0}
tr:nth-child(even) td{background:#f1f7ff}
td.n{text-align:center;font-weight:700;color:var(--navy);font-size:26px}
td.nm{font-weight:700;color:var(--ink)}
td.nm .row{display:flex;align-items:center;gap:12px;min-width:0}
td.nm .row .ic{flex:none;color:var(--navy);background:#dbe9fa;border-radius:12px;padding:7px;width:46px;height:46px}
td.nm .tx{min-width:0;overflow:hidden}
td.nm .l1{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:22px;line-height:1.4}
td.nm .l2{white-space:nowrap;overflow:hidden;font-size:20px;font-weight:400;color:var(--mute)}
td.num{text-align:center;font-weight:700;white-space:nowrap}
.dark{margin-top:20px;display:flex;gap:18px;align-items:stretch}
.totals{flex:1.25;background:linear-gradient(180deg,var(--navy) 0%,var(--navy2) 100%);border-radius:24px;padding:16px;display:flex;flex-direction:column;gap:12px;color:#fff}
.trow{flex:1;border:2px solid rgba(255,255,255,.45);border-radius:18px;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:84px}
.trow .lb{display:flex;align-items:center;gap:10px;font-size:25px;font-weight:700;white-space:nowrap}
.trow .vl{display:flex;align-items:baseline;gap:10px;white-space:nowrap}
.trow .vl b{font-size:36px}.trow .vl small{font-size:22px;opacity:.9}
.trow.big{flex:1.7;background:rgba(255,255,255,.08);flex-direction:column;align-items:stretch;justify-content:center;gap:4px}
.trow.big .bt{display:flex;align-items:center;justify-content:space-between;gap:12px}
.trow .words{font-size:22px;opacity:.95;text-align:right;line-height:1.4}
.trow.msg{justify-content:flex-start;gap:12px;font-size:22px;font-weight:700;line-height:1.4}
.trow.msg .ic{flex:none;color:#7fe3b5}
.trow.big .vl b{font-size:60px;line-height:1.1}
.notes{flex:1;overflow:hidden;min-width:0;border:2px solid var(--line);border-radius:22px;background:#fff;padding:16px 22px}
.notes h3{font-size:30px;color:var(--navy);display:flex;align-items:center;gap:10px;margin-bottom:8px}
.notes ol{list-style-type:persian}.notes li{font-size:21px;color:var(--ink);margin-inline-start:22px;margin-bottom:4px;line-height:1.55}
.payrow{margin-top:20px;display:flex;gap:14px}
.pf{flex:1;min-width:0;border:2px solid var(--line);border-radius:20px;background:var(--soft);padding:12px 18px}
.pf small{display:flex;align-items:center;gap:8px;font-size:20px;color:var(--mute)}.pf small .ic{color:var(--navy)}
.pf b{display:block;margin-top:2px;font-size:24px;color:var(--navy);white-space:nowrap;overflow:hidden}
.pf b.ltr{direction:ltr;text-align:right}
.pf.card{flex:1.1}.pf.sheba{flex:1.7}.pf.sheba b{font-size:21px}.pf.owner{flex:.9}
.logo{height:96px;max-width:300px;object-fit:contain}
.logo.hd{width:270px;height:121px;max-width:none;flex:none}
.contact{margin-top:18px;border:2px solid var(--line);border-radius:22px;background:rgba(255,255,255,.9);padding:14px 22px;text-align:center}
.contact .ln{display:flex;flex-wrap:wrap;justify-content:center;gap:6px 26px;font-size:21px;color:var(--ink)}
.contact .it{display:inline-flex;align-items:center;gap:8px;max-width:100%}.contact .it .ic{color:var(--navy);flex:none}
.contact .it span{overflow:hidden;text-overflow:ellipsis}
.contact .th{margin-top:6px;font-size:23px;font-weight:700;color:var(--navy)}
.foot{margin-top:20px;display:flex;justify-content:space-between;align-items:center;gap:18px}
.fdate{border:2px solid var(--line);border-radius:20px;background:var(--soft);padding:12px 20px;display:flex;align-items:center;gap:14px}
.fdate .ic{color:var(--navy)}.fdate small{display:block;font-size:20px;color:var(--mute)}.fdate b{font-size:26px;color:var(--navy)}
.sign{text-align:center;min-width:360px;padding-bottom:6px}
.sign small{font-size:22px;color:var(--mute);display:block}
.sign .ln{display:flex;align-items:center;gap:14px;margin-top:30px;font-weight:700;color:var(--navy);font-size:26px}
.sign .ln i{flex:1;height:2px;background:var(--navy);opacity:.55}
.badge{display:inline-flex;align-items:center;gap:8px;border-radius:999px;padding:4px 18px;font-weight:700;font-size:23px;border:2px solid}
.badge.good{color:var(--good);background:#e5f7ef;border-color:#8fd8b9}.badge.bad{color:var(--bad);background:#fdeaea;border-color:#f0a8a8}
.pill{display:inline-flex;align-items:center;gap:8px;border-radius:999px;padding:2px 16px;font-size:22px;background:#dbe9fa;color:var(--navy);font-weight:700}
"""

_WAVE_TOP = ('<svg class="wave top" viewBox="0 0 1080 170" preserveAspectRatio="none">'
             '<defs><linearGradient id="a" x1="0" x2="1"><stop offset="0" stop-color="#6fb1f2"/><stop offset="1" stop-color="#2f7fe0"/></linearGradient></defs>'
             '<path d="M0 0H1080V38C930 78 800 8 640 40C470 76 300 120 150 96C90 86 40 70 0 88Z" fill="#cfe4fb"/>'
             '<path d="M0 0H1080V16C980 44 880 4 760 22C600 48 450 84 300 68C190 56 90 36 0 60Z" fill="url(#a)" opacity=".75"/>'
             '<path d="M0 0H1080V6C990 22 900 0 820 8C650 26 480 56 320 44C200 36 100 20 0 34Z" fill="#1c5fc0"/></svg>')
_WAVE_BOT = ('<svg class="wave bot" viewBox="0 0 1080 150" preserveAspectRatio="none">'
             '<path d="M0 150V70C120 30 260 20 420 52C580 84 700 92 840 60C940 38 1020 40 1080 54V150Z" fill="#cfe4fb"/>'
             '<path d="M0 150V96C150 62 290 70 450 98C600 124 760 120 900 90C980 74 1040 76 1080 86V150Z" fill="#6fb1f2" opacity=".7"/>'
             '<path d="M0 150V122C160 96 300 110 470 128C640 146 800 130 940 112C1010 104 1050 106 1080 112V150Z" fill="#1c5fc0"/></svg>')

_ILLUS = ('<svg class="illus" viewBox="0 0 260 190" aria-hidden="true">'
          '<ellipse cx="130" cy="176" rx="118" ry="10" fill="#cfe4fb"/>'
          '<rect x="20" y="70" width="170" height="104" rx="6" fill="#e8f2fe" stroke="#0b3d86" stroke-width="4"/>'
          '<path d="M10 70L30 22H180L200 70Z" fill="#fff" stroke="#0b3d86" stroke-width="4" stroke-linejoin="round"/>'
          '<path d="M30 22L22 70M72 22L66 70M115 22V70M158 22L164 70M180 22L188 70" stroke="#0b3d86" stroke-width="4"/>'
          '<path d="M30 22L22 70H66L72 22Z M115 22V70H164L158 22Z" fill="#1d6fd6" stroke="#0b3d86" stroke-width="4" stroke-linejoin="round"/>'
          '<path d="M10 70q14 16 28 0q14 16 28 0q14 16 28 0q14 16 28 0q14 16 28 0q14 16 28 0q8 10 16 0" fill="#0b3d86"/>'
          '<rect x="34" y="100" width="62" height="74" rx="4" fill="#fff" stroke="#0b3d86" stroke-width="4"/>'
          '<rect x="108" y="100" width="66" height="38" rx="4" fill="#bcd9f8" stroke="#0b3d86" stroke-width="4"/>'
          '<rect x="108" y="146" width="66" height="28" rx="3" fill="#1d6fd6" stroke="#0b3d86" stroke-width="3"/>'
          '<rect x="176" y="60" width="62" height="114" rx="12" fill="#0b3d86"/>'
          '<rect x="182" y="72" width="50" height="86" rx="5" fill="#9fd0ff"/>'
          '<rect x="193" y="64" width="28" height="4" rx="2" fill="#6fb1f2"/>'
          '<path d="M189 140l12-24 9 14 7-9 8 19z" fill="#1d6fd6" opacity=".85"/><circle cx="214" cy="88" r="7" fill="#fff"/>'
          '<circle cx="207" cy="166" r="4" fill="#6fb1f2"/>'
          '</svg>')

NOTE_LINES = (
    "پس از واریز، تصویر رسید را در همین گفتگو برای ما بفرستید.",
    "در صورت هرگونه سؤال با پشتیبانی فروشگاه در ارتباط باشید.",
)
PRICE_NOTES = (
    "قیمت‌ها به ریال است و تا زمان تأیید نهایی ممکن است تغییر کند.",
    "موجودی و قیمت لحظه‌ای است.",
)
NO_PAYMENT_NOTE = "جزئیات پرداخت در پیام بعدی برای شما ارسال می‌شود."


# ----------------------------------------------------------------- page parts
def _page(body: str, height: int) -> str:
    css = (_CSS.replace("__H__", str(height)).replace("__ROW__", str(_H_ROW))
           .replace("__FR__", _font_b64(FONT_REGULAR)).replace("__FB__", _font_b64(FONT_BOLD)))
    return (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
            f'<style>{css}</style></head><body>{_WAVE_TOP}{_WAVE_BOT}'
            f'<div class="page">{body}</div></body></html>')


def _head(shop: str, title: str, number_label: str, number, date_text: str, cust_label="خریدار",
          customer: str = "") -> str:
    cust = f'<div class="meta">{icon("user", 26)}<b>{esc(cust_label)}:</b><span class="v">{esc(customer)}</span></div>' if customer else ""
    num = (f'<div class="meta">{icon("file-invoice", 26)}<b>{esc(number_label)}:</b>'
           f'<span class="v">{esc(fa_digits(number))}</span></div>') if number_label else ""
    mark = _logo_tag("logo hd") or _ILLUS      # the logo replaces the store illustration
    return (f'<div class="head">{mark}<div class="brand"><div class="t">{esc(shop)}</div>'
            f'<div class="t" style="font-size:30px;font-weight:400">{esc(title)}</div>'
            f'<div class="s">موبایل و لوازم جانبی</div></div>'
            f'<div class="metabox">{num}'
            f'<div class="meta">{icon("calendar", 26)}<b>تاریخ:</b><span class="v">{esc(date_text)}</span></div>'
            f'{cust}</div></div><div class="sep"></div>')


def _date_box(date_text: str) -> str:
    return (f'<div class="fdate">{icon("calendar", 44)}<div><small>تاریخ صدور</small>'
            f'<b>{esc(date_text)}</b></div></div>')


def _foot_price(date_text: str, contact: dict | None) -> str:
    """Price card footer: issue date and the shop contact band (address, phone, bot id)."""
    return f'<div class="foot">{_date_box(date_text)}</div>{_contact_box(contact)}'


def _logo_tag(cls: str = "logo") -> str:
    tag = _logo_html()
    return tag.replace('class="logo"', f'class="{cls}"') if tag else ""


@functools.lru_cache(maxsize=1)
def _logo_html() -> str:
    """The shop logo as an inline image; empty when the file is missing/unreadable."""
    try:
        raw = LOGO_FILE.read_bytes()
    except OSError:
        return ""
    if not raw.startswith(b"\x89PNG"):
        return ""
    return f'<img class="logo" alt="" src="data:image/png;base64,{base64.b64encode(raw).decode("ascii")}">'


def _contact_box(contact: dict | None) -> str:
    """Shop address, phone, Bale bot id and a thank-you line (all from the shop config;
    empty entries are skipped, no entries at all = no box)."""
    c = contact or {}
    items = []
    for key, ic in (("address", "map-pin"), ("phone", "phone"), ("bot_id", "message-circle")):
        value = str(c.get(key) or "").strip()
        if value:
            shown = fa_digits(value) if key == "phone" else value
            items.append(f'<span class="it">{icon(ic, 24)}<span>{esc(shown)}</span></span>')
    thanks = str(c.get("thanks") or "").strip()
    if not items and not thanks:
        return ""
    th = f'<div class="th">{esc(thanks)}</div>' if thanks else ""
    return f'<div class="contact"><div class="ln">{"".join(items)}</div>{th}</div>'


def _foot_invoice(date_text: str, contact: dict | None) -> str:
    """Invoice footer: issue date, the shop logo (where the signature box used to be)
    and the contact band."""
    return (f'<div class="foot">{_date_box(date_text)}{_logo_tag()}</div>{_contact_box(contact)}')


def _foot_height(contact: dict | None) -> int:
    return 110 + (20 + 130 if _contact_box(contact) else 0)


def _th(label: str, ic: str) -> str:
    return f'<th><span class="in">{icon(ic, 26)}{esc(label)}</span></th>'


def _items_table(items, currency: str) -> str:
    rows = []
    for idx, it in enumerate(items, 1):
        qty = float(it.get("qty") or 0)
        unit = float(it.get("unit_price") or 0)
        name = it.get("name") or ""
        rows.append(
            f'<tr><td class="n">{fa_digits(idx)}</td>'
            f'<td class="nm"><div class="row">{icon(_item_icon(name), 30)}'
            f'<div class="tx"><div class="l1">{esc(name)}</div></div></div></td>'
            f'<td class="num">{fa_num(qty)}</td><td class="num">{fa_num(unit)}</td>'
            f'<td class="num">{fa_num(qty * unit)}</td></tr>')
    return ('<table><colgroup><col style="width:9%"><col style="width:37%"><col style="width:12%">'
            '<col style="width:21%"><col style="width:21%"></colgroup><thead><tr>'
            f'{_th("ردیف", "hash")}{_th("شرح کالا", "list-details")}{_th("تعداد", "package")}'
            f'{_th(f"قیمت واحد ({currency})", "coins")}{_th(f"جمع ({currency})", "cash")}'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>')


def _totals(rows: list[tuple[str, str, str, str]], big: tuple[str, str, str, str],
            words: str = "", message: str = "") -> str:
    """rows: (icon, label, value, unit); big: (icon, label, value, unit) as one row with
    optional amount-in-words under it; message: a full-width status row."""
    out = []
    for ic, label, value, unit in rows:
        u = f"<small>{esc(unit)}</small>" if unit else ""
        out.append(f'<div class="trow"><span class="lb">{icon(ic, 30)}{esc(label)}</span>'
                   f'<span class="vl"><b>{esc(value)}</b>{u}</span></div>')
    if message:
        # one line: the font shrinks with the text; it wraps only if even the smallest size cannot fit
        n = len(message)
        size = 24 if n <= 34 else 21 if n <= 44 else 19 if n <= 52 else 17 if n <= 62 else 17
        nowrap = "white-space:nowrap;" if n <= 62 else ""
        out.append(f'<div class="trow msg">{icon("circle-check", 30)}'
                   f'<span style="font-size:{size}px;{nowrap}">{esc(message)}</span></div>')
    ic, label, value, unit = big
    w = f'<div class="words">{esc(words)}</div>' if words else ""
    out.append(f'<div class="trow big"><div class="bt"><span class="lb">{icon(ic, 34)}{esc(label)}</span>'
               f'<span class="vl"><b>{esc(value)}</b><small>{esc(unit)}</small></span></div>{w}</div>')
    return f'<div class="totals">{"".join(out)}</div>'


def _notes(lines, extra: str = "") -> str:
    li = "".join(f"<li>{esc(x)}</li>" for x in lines)
    return f'<div class="notes"><h3>{icon("notes", 32)}توضیحات</h3>{extra}<ol>{li}</ol></div>'


def _payment_fields(payment: dict | None) -> list[tuple[str, str, str, str, bool]]:
    """(css class, icon, label, value, ltr) for each configured payment field."""
    p = payment or {}
    out = []
    digits = "".join(ch for ch in str(p.get("card_number") or "").translate(
        str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")) if ch.isdigit())
    if digits:
        out.append(("card", "credit-card", "شمارهٔ کارت", " ".join(digits[i:i + 4] for i in range(0, len(digits), 4)), True))
    sheba = str(p.get("sheba") or "").replace(" ", "").upper()
    if sheba:
        out.append(("sheba", "building-bank", "شمارهٔ شبا", sheba, True))
    owner = str(p.get("owner") or "").strip()
    if owner:
        out.append(("owner", "user-circle", "صاحب حساب", owner, False))
    return out


def _payment_box(payment: dict | None) -> str:
    """The payment section; nothing at all when no field is configured."""
    fields = _payment_fields(payment)
    if not fields:
        return ""
    cells = "".join(
        f'<div class="pf {cls}"><small>{icon(ic, 22)}{esc(label)}</small>'
        f'<b class="{"ltr" if ltr else ""}">{esc(value)}</b></div>'
        for cls, ic, label, value, ltr in fields)
    return f'<div class="payrow">{cells}</div>'


def _safe(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - never break the chat flow
            logger.warning("cards: %s failed (%s) - falling back to text", fn.__name__, type(exc).__name__)
            return None
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# Fixed block heights (px) used to size the page; rows never wrap (2-line clamp).
_H_HEAD, _H_TABLE_HEAD, _H_ROW = 250, 70, 96
_H_DARK, _H_FOOT, _H_BOT = 340, 150, 150
_H_PAY = 110


def _height(n_rows: int, dark: int = _H_DARK, pay: int = 0, foot: int = _H_FOOT) -> int:
    return (34 + _H_HEAD + _H_TABLE_HEAD + n_rows * _H_ROW + 20 + (pay + 20 if pay else 0)
            + dark + 20 + foot + 60)


# ----------------------------------------------------------------- price card
@_safe
def price_card(*, shop: str, name: str, color: str, price, in_stock: bool,
               contact: dict | None = None, currency: str = "ریال", date=None) -> bytes | None:
    """Product, selected color, price in Rial and a stock badge."""
    d = fa_digits(shamsi_date(date))
    badge = (f'<span class="badge good">{icon("circle-check", 24)}موجود</span>' if in_stock
             else f'<span class="badge bad">{icon("circle-x", 24)}ناموجود</span>')
    color_cell = f'<span class="pill">{icon("palette", 22)}{esc(color)}</span>' if color else "—"
    table = (
        '<table><colgroup><col style="width:46%"><col style="width:27%"><col style="width:27%"></colgroup>'
        f'<thead><tr>{_th("کالا", "device-mobile")}{_th("رنگ", "palette")}{_th("وضعیت", "package")}</tr></thead>'
        f'<tbody><tr style="height:110px"><td class="nm"><div class="row">{icon(_item_icon(name), 34)}'
        f'<div class="tx"><div class="l1" style="font-size:25px">{esc(name)}</div></div></div></td>'
        f'<td class="num">{color_cell}</td><td class="num">{badge}</td></tr></tbody></table>')
    totals = _totals([], ("cash", "قیمت", fa_num(price), currency))
    dark = 230
    body = (_head(shop, "کارت قیمت", "", "", d) + table
            + f'<div class="dark" style="height:{dark}px">{totals}{_notes(PRICE_NOTES)}</div>'
            + _foot_price(d, contact))
    h = 34 + _H_HEAD + _H_TABLE_HEAD + 110 + 20 + dark + 20 + _foot_height(contact) + 60
    return _screenshot(_page(body, h), h)


# ---------------------------------------------------------------- pre-invoice
@_safe
def pre_invoice_card(*, shop: str, order_id, items, total, payment: dict | None = None,
                     contact: dict | None = None, currency: str = "ریال",
                     date=None, customer: str = "") -> bytes | None:
    """Pre-invoice (placed order): lines, total (digits + words) and, when configured, the
    payment details. ``payment`` = {card_number, sheba, owner}; ``contact`` = {address,
    phone, bot_id, thanks}."""
    items = list(items or [])[:10]
    d = fa_digits(shamsi_date(date))
    pay_html = _payment_box(payment)
    totals = _totals(
        [("package", "تعداد اقلام", fa_digits(len(items)), "قلم")],
        ("cash", "مبلغ قابل پرداخت", fa_num(total), currency),
        words=amount_in_words(total, currency),
        message=f"سفارش شما ثبت شد — شمارهٔ پیگیری: {fa_digits(order_id)}")
    lines = NOTE_LINES if pay_html else (NO_PAYMENT_NOTE,) + NOTE_LINES[1:]
    body = (_head(shop, "پیش‌فاکتور", "شماره سفارش", order_id, d, customer=customer)
            + _items_table(items, currency) + pay_html
            + f'<div class="dark" style="height:{_H_DARK + 40}px">{totals}{_notes(lines)}</div>'
            + _foot_invoice(d, contact))
    h = _height(len(items), dark=_H_DARK + 40, pay=_H_PAY if pay_html else 0, foot=_foot_height(contact))
    return _screenshot(_page(body, h), h)


# -------------------------------------------------------------- final invoice
@_safe
def final_invoice_card(*, shop: str, order_id, items, total, partial: bool = False,
                       invoice_numbers=None, contact: dict | None = None, currency: str = "ریال",
                       date=None, customer: str = "") -> bytes | None:
    """Sales invoice (the order was invoiced in accounting). Lines/prices are the order's own
    (see PROGRESS). ``invoice_numbers`` = accounting invoice numbers (facto.Numfact), all of
    them for a partially invoiced order."""
    items = list(items or [])[:10]
    d = fa_digits(shamsi_date(date))
    nums = [str(n).strip() for n in (invoice_numbers or []) if str(n).strip()]
    message = "فاکتور شما صادر شد" + (
        " — شمارهٔ فاکتور: " + "، ".join(fa_digits(n) for n in nums) if nums else "")
    totals = _totals(
        [("package", "تعداد اقلام", fa_digits(len(items)), "قلم")],
        ("cash", "جمع سفارش" if partial else "جمع فاکتور", fa_num(total), currency),
        words=amount_in_words(total, currency), message=message)
    badge = ('<span class="badge good">' + icon("circle-check", 24)
             + ("بخشی از سفارش فاکتور شد" if partial else "فاکتور صادر شد") + "</span>")
    lines = ("ارسال پس از آماده‌سازی انجام می‌شود.", NOTE_LINES[1])
    body = (_head(shop, "فاکتور فروش", "شماره سفارش", order_id, d, customer=customer)
            + _items_table(items, currency)
            + f'<div class="dark" style="height:{_H_DARK + 40}px">{totals}'
              f'{_notes(lines, f"<p style=margin-bottom:8px>{badge}</p>")}</div>'
            + _foot_invoice(d, contact))
    h = _height(len(items), dark=_H_DARK + 40, foot=_foot_height(contact))
    return _screenshot(_page(body, h), h)
