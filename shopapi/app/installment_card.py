"""v2.18.1 the customer's installment card: HTML, made into a PNG by a headless browser (Edge on the
Windows server, as the bot's own cards), so Persian shaping is the browser's job.

The same card for ShopAdmin, the bot and the mini app. It is made from
:func:`installments.customer_view` alone, so it cannot show a rate or an interest.
Returns None when no image can be made: the caller then sends :func:`installments.customer_text`.
"""
from __future__ import annotations

import base64
import contextlib
import html
import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from functools import lru_cache
from pathlib import Path

from . import installments

logger = logging.getLogger("shopapi.installment_card")

ASSETS = Path(__file__).with_name("data") / "card"
WIDTH = 1080
WINDOW_PAD = 200      # a headless window is a little shorter than asked: rendered taller and cropped
RENDER_TIMEOUT = 40
OUTPUT_WAIT = 15.0
_WIN_BROWSERS = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
)
_PATH_BROWSERS = ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser", "chrome")


def find_browser() -> str | None:
    override = os.environ.get("BOT_CARD_BROWSER", "").strip()
    if override:
        return override if Path(override).exists() else None
    if sys.platform == "win32":
        for raw in _WIN_BROWSERS:
            path = Path(os.path.expandvars(raw))
            if path.exists():
                return str(path)
    for name in _PATH_BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    return None


@lru_cache(maxsize=4)
def _asset_b64(name: str) -> str:
    return base64.b64encode((ASSETS / name).read_bytes()).decode("ascii")


def _esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def card_height(view: dict) -> int:
    return 980 + 84 * len(view["checks"]) + (96 if view["phone_name"] else 0)


def card_html(view: dict, *, shop: str = "عصر ارتباطات ۲", phone: str = "") -> str:
    """The card's page, from a customer view."""
    money = installments.fa_money
    digits = installments.fa_text
    dates = view["dates"]
    rows = "".join(
        f'<tr><td>{digits(number)}</td>'
        f'<td><bdi>{digits(dates[number - 1]) if number <= len(dates) else "—"}</bdi></td>'
        f'<td class="value"><bdi>{money(amount)}</bdi></td></tr>'
        for number, amount in enumerate(view["checks"], 1))
    phone_line = (f'<div class="phone-name"><bdi>{_esc(view["phone_name"])}</bdi></div>'
                  if view["phone_name"] else "")
    contact = f'<span>تلفن: <bdi>{_esc(digits(phone))}</bdi></span>' if phone else ""
    return f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>
@font-face{{font-family:Vazirmatn;font-weight:400;src:url(data:font/ttf;base64,{_asset_b64("Vazirmatn-Regular.ttf")})}}
@font-face{{font-family:Vazirmatn;font-weight:700;src:url(data:font/ttf;base64,{_asset_b64("Vazirmatn-Bold.ttf")})}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{width:{WIDTH}px;font-family:Vazirmatn,sans-serif;color:#0f1f3d;
background:linear-gradient(115deg,#6d3bf5 0%,#2f6fed 55%,#14b8c4 100%);padding:56px}}
.sheet{{background:#fff;border-radius:44px;padding:56px;box-shadow:0 24px 70px rgba(10,20,60,.35)}}
.top{{display:flex;align-items:center;gap:28px;margin-bottom:36px}}
.top img{{width:112px;height:112px;object-fit:contain}}
.shop{{font-size:50px;font-weight:700;line-height:1.3}}
.kind{{font-size:32px;color:#51617f}}
.phone-name{{background:#eef2ff;border-radius:24px;padding:20px 32px;font-size:40px;font-weight:700;
margin-bottom:28px;text-align:center;color:#3a2bb8}}
.line{{display:flex;justify-content:space-between;align-items:baseline;padding:26px 8px;
border-bottom:2px solid #e6ebf5;font-size:36px}}
.line b{{font-size:46px}}
.label{{font-size:32px;color:#51617f;margin:28px 8px 12px}}
table{{width:100%;border-collapse:separate;border-spacing:0 10px;font-size:36px}}
th{{font-size:30px;font-weight:400;color:#51617f;padding:0 24px;text-align:right}}
td{{background:#f4f7fd;padding:16px 24px}}
td:first-child{{border-radius:0 20px 20px 0;font-weight:700}}
td:last-child{{border-radius:20px 0 0 20px}}
.value{{font-weight:700;font-size:40px}}
small{{font-size:28px;font-weight:400;color:#51617f}}
.total{{margin-bottom:12px;border-radius:30px;padding:34px 40px;color:#fff;display:flex;
justify-content:space-between;align-items:baseline;
background:linear-gradient(115deg,#6d3bf5,#2f6fed 60%,#14b8c4)}}
.total span{{font-size:36px}} .total b{{font-size:58px}} .total small{{color:#e6ecff}}
.foot{{display:flex;justify-content:space-between;margin-top:30px;font-size:28px;color:#51617f}}
</style></head><body><div class="sheet">
<div class="top"><img alt="" src="data:image/png;base64,{_asset_b64("logo.png")}">
<div><div class="shop">{_esc(shop)}</div><div class="kind">پیشنهاد خرید اقساطی</div></div></div>
{phone_line}
<div class="total"><span>جمع کل</span><b><bdi>{money(view["grand_total"])}</bdi> <small>ریال</small></b></div>
<div class="line"><span>پیش‌پرداخت</span><b><bdi>{money(view["down"])}</bdi> <small>ریال</small></b></div>
<div class="label">چک‌ها</div>
<table><thead><tr><th>شماره</th><th>تاریخ</th><th>مبلغ (ریال)</th></tr></thead><tbody>{rows}</tbody></table>
<div class="foot"><span>تاریخ: <bdi>{_esc(digits(view["date"]))}</bdi></span>{contact}</div>
</div></body></html>"""


@contextlib.contextmanager
def _work_dir():
    # Not mkdtemp: its owner-only ACL on Windows is one Edge's sandbox cannot use.
    path = Path(tempfile.gettempdir()) / f"shopcard_{uuid.uuid4().hex}"
    os.makedirs(path)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _wait_for_file(path: Path, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    last = -1
    while True:
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        if size > 0 and size == last:
            return True
        if time.monotonic() >= deadline:
            return size > 0
        last = size
        time.sleep(0.2)


def _crop_to_sheet(png: bytes) -> bytes | None:
    """Cut the page just below the white sheet (the window is taller than the page)."""
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
    if image.width != WIDTH:
        return None
    # the sheet is white on a coloured page: its last white row, plus the page's own padding
    probe = WIDTH // 2
    bottom = 0
    for y in range(image.height - 1, -1, -1):
        if min(image.getpixel((probe, y))) > 245:
            bottom = y
            break
    if not bottom:
        return None
    out = io.BytesIO()
    image.crop((0, 0, WIDTH, min(bottom + 56, image.height))).save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_png(view: dict, *, shop: str = "عصر ارتباطات ۲", phone: str = "") -> bytes | None:
    """PNG bytes, or None when there is no browser or anything fails: never raises."""
    try:
        browser = find_browser()
        if not browser:
            logger.warning("installment card: no Chromium/Edge found")
            return None
        with _work_dir() as folder:
            page, out = folder / "card.html", folder / "card.png"
            page.write_text(card_html(view, shop=shop, phone=phone), encoding="utf-8")
            command = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                       "--no-sandbox", "--no-first-run", "--disable-extensions",
                       "--disable-background-networking", "--force-device-scale-factor=1",
                       f"--window-size={WIDTH},{card_height(view) + WINDOW_PAD}",
                       "--virtual-time-budget=3000", f"--user-data-dir={folder / 'profile'}",
                       f"--screenshot={out}", page.as_uri()]
            subprocess.run(command, check=False, timeout=RENDER_TIMEOUT,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not _wait_for_file(out, OUTPUT_WAIT):
                logger.warning("installment card: the browser made no image")
                return None
            data = out.read_bytes()
        return _crop_to_sheet(data) if data.startswith(b"\x89PNG") else None
    except Exception as exc:  # noqa: BLE001 - a card must never break the request
        logger.warning("installment card failed: %s", type(exc).__name__)
        return None
