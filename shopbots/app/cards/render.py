"""Premium dark image cards rendered with Pillow (offline, no system fonts).

Persian shaping: arabic-reshaper joins the letters, python-bidi puts the line in
visual order, and Pillow draws it with the BASIC layout engine (so the result is
identical with or without libraqm - nothing to install on Windows). Vazirmatn
(OFL, bundled in ``assets/``) has the Arabic presentation forms this needs.

Every public function returns PNG bytes, or ``None`` when anything fails: the
caller then sends the plain text message instead.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .jdate import shamsi_date

logger = logging.getLogger("shopbots.cards")

ASSETS = Path(__file__).resolve().parent / "assets"
FONT_REGULAR = ASSETS / "Vazirmatn-Regular.ttf"
FONT_BOLD = ASSETS / "Vazirmatn-Bold.ttf"
LOGO = ASSETS / "logo.png"          # optional; the wordmark is used when absent

W = 1080
PAD = 56
BG = (5, 7, 12)
PANEL = (255, 255, 255, 14)         # frosted glass: translucent white
PANEL_EDGE = (255, 255, 255, 34)
TEXT = (238, 242, 250)
MUTED = (140, 152, 176)
ACCENT = (59, 130, 246)             # deep blue
ACCENT_DEEP = (29, 78, 216)
GOOD = (52, 211, 153)
BAD = (248, 113, 113)

_FA_DIGITS = str.maketrans("0123456789,.", "۰۱۲۳۴۵۶۷۸۹٬٫")


def fa_num(value) -> str:
    """12345678 -> ۱۲٬۳۴۵٬۶۷۸ (display digits)."""
    try:
        return f"{float(value):,.0f}".translate(_FA_DIGITS)
    except (TypeError, ValueError):
        return "۰"


def fa_digits(text) -> str:
    return str(text).translate(_FA_DIGITS)


def shape(text: str) -> str:
    """Logical Persian/Latin text -> visual string ready for Pillow."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped, base_dir="R")


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        str(FONT_BOLD if bold else FONT_REGULAR), size, layout_engine=ImageFont.Layout.BASIC
    )


class Canvas:
    def __init__(self, height: int):
        self.h = height
        self.img = Image.new("RGBA", (W, height), BG + (255,))
        self._backdrop()
        self.d = ImageDraw.Draw(self.img)

    def _backdrop(self) -> None:
        glow = Image.new("RGBA", (W, self.h), (0, 0, 0, 0))
        g = ImageDraw.Draw(glow)
        g.ellipse((-260, -320, 640, 380), fill=ACCENT_DEEP + (120,))
        g.ellipse((560, self.h - 360, 1340, self.h + 260), fill=ACCENT + (60,))
        self.img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))

    def panel(self, box, radius=34, fill=PANEL, edge=PANEL_EDGE) -> None:
        x0, y0, x1, y1 = box
        layer = Image.new("RGBA", (W, self.h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle(box, radius, fill=fill, outline=edge, width=2)
        self.img.alpha_composite(layer)
        self.d = ImageDraw.Draw(self.img)

    def pill(self, box, color, radius=None) -> None:
        x0, y0, x1, y1 = box
        layer = Image.new("RGBA", (W, self.h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle(
            box, radius or (y1 - y0) // 2, fill=color + (40,), outline=color + (150,), width=2
        )
        self.img.alpha_composite(layer)
        self.d = ImageDraw.Draw(self.img)

    def fit(self, text: str, bold: bool, size: int, max_w: int, min_size: int = 20):
        """The font that fits ``text`` into ``max_w`` (shrinks, then truncates)."""
        shaped = shape(text)
        s = size
        while s > min_size:
            f = _font(bold, s)
            if f.getlength(shaped) <= max_w:
                return f, shaped
            s -= 2
        f = _font(bold, min_size)
        raw = str(text)
        while len(raw) > 1 and f.getlength(shape(raw + "…")) > max_w:
            raw = raw[:-1]
        return f, shape(raw.rstrip() + "…")

    def text_r(self, x, y, text, size, color=TEXT, bold=False, max_w=None) -> int:
        """Right-aligned at ``x``; returns the text's left edge."""
        if max_w:
            font, shaped = self.fit(text, bold, size, max_w)
        else:
            font, shaped = _font(bold, size), shape(text)
        self.d.text((x, y), shaped, font=font, fill=color, anchor="ra")
        return int(x - font.getlength(shaped))

    def text_l(self, x, y, text, size, color=TEXT, bold=False, max_w=None) -> int:
        if max_w:
            font, shaped = self.fit(text, bold, size, max_w)
        else:
            font, shaped = _font(bold, size), shape(text)
        self.d.text((x, y), shaped, font=font, fill=color, anchor="la")
        return int(x + font.getlength(shaped))

    def text_c(self, cx, y, text, size, color=TEXT, bold=False, max_w=None) -> None:
        if max_w:
            font, shaped = self.fit(text, bold, size, max_w)
        else:
            font, shaped = _font(bold, size), shape(text)
        self.d.text((cx, y), shaped, font=font, fill=color, anchor="ma")

    def rule(self, y, x0=PAD + 36, x1=W - PAD - 36) -> None:
        layer = Image.new("RGBA", (W, self.h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).line((x0, y, x1, y), fill=(255, 255, 255, 28), width=2)
        self.img.alpha_composite(layer)
        self.d = ImageDraw.Draw(self.img)

    def header(self, shop: str, tag: str) -> int:
        """Wordmark on the right, card type on the left. Returns the next y."""
        right = W - PAD
        if LOGO.exists():
            try:
                logo = Image.open(LOGO).convert("RGBA")
                logo.thumbnail((72, 72))
                self.img.alpha_composite(logo, (right - logo.width, PAD))
                self.d = ImageDraw.Draw(self.img)
                right -= logo.width + 18
            except Exception:  # noqa: BLE001 - a bad logo never blocks a card
                logger.warning("cards: logo.png unreadable - using the wordmark")
        else:
            dot = 56
            self.d.rounded_rectangle((right - dot, PAD + 4, right, PAD + 4 + dot), 18, fill=ACCENT)
            self.text_c(right - dot / 2, PAD + 6, (shop or "ع")[:1], 36, (255, 255, 255), True)
            right -= dot + 18
        self.text_r(right, PAD + 2, shop or "", 40, TEXT, True, max_w=560)
        self.text_l(PAD, PAD + 12, tag, 30, MUTED)
        return PAD + 96

    def png(self) -> bytes:
        out = io.BytesIO()
        self.img.convert("RGB").save(out, format="PNG", optimize=True)
        return out.getvalue()


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


def _footer(c: Canvas, y: int, text: str, date_text: str) -> None:
    c.text_r(W - PAD, y, text, 24, MUTED, max_w=W - 2 * PAD - 240)
    c.text_l(PAD, y, date_text, 24, MUTED)


# ----------------------------------------------------------------- price card
@_safe
def price_card(*, shop: str, name: str, color: str, price, in_stock: bool,
               currency: str = "ریال", date=None) -> bytes | None:
    """Product, selected color, price in Rial and a stock badge."""
    c = Canvas(640)
    y = c.header(shop, "کارت قیمت")
    box = (PAD, y + 8, W - PAD, 548)
    c.panel(box)
    r = W - PAD - 44
    inner = W - 2 * PAD - 88
    c.text_r(r, y + 48, name, 52, TEXT, True, max_w=inner)
    # color pill + stock badge
    row_y = y + 138
    right = r
    label = f"رنگ: {color}" if color else ""
    if label:
        f, s = c.fit(label, False, 28, 420)
        w = int(f.getlength(s)) + 52
        c.pill((right - w, row_y, right, row_y + 54), ACCENT)
        c.d.text((right - w / 2, row_y + 8), s, font=f, fill=(190, 215, 255), anchor="ma")
        right -= w + 16
    badge = "موجود" if in_stock else "ناموجود"
    col = GOOD if in_stock else BAD
    f = _font(True, 28)
    s = shape(badge)
    w = int(f.getlength(s)) + 64
    c.pill((right - w, row_y, right, row_y + 54), col)
    c.d.ellipse((right - w + 18, row_y + 20, right - w + 32, row_y + 34), fill=col)
    c.d.text((right - w + 44, row_y + 8), s, font=f, fill=col, anchor="la")
    c.rule(y + 232)
    c.text_r(r, y + 256, "قیمت", 28, MUTED)
    amount = fa_num(price)
    right_edge = c.text_r(r, y + 296, currency, 34, MUTED)
    f = _font(True, 92)
    s = shape(amount)
    c.d.text((right_edge - 18, y + 262), s, font=f, fill=(255, 255, 255), anchor="ra")
    c.d.line((box[0] + 44, box[3] - 28, box[0] + 44 + 140, box[3] - 28), fill=ACCENT, width=6)
    _footer(c, 578, "قیمت لحظه‌ای است و ممکن است تغییر کند", fa_digits(shamsi_date(date)))
    return c.png()


# --------------------------------------------------------------- order tables
def _row_h(it) -> int:
    return 92 if it.get("variant") else 66


def _table_h(items) -> int:
    return 252 + sum(_row_h(i) for i in items)


def _items_table(c: Canvas, y: int, items, currency: str) -> int:
    """Rows: name (right), qty, unit price, line total (left). Returns next y."""
    r = W - PAD - 44
    c.text_r(r, y, "کالا", 24, MUTED)
    c.text_r(r - 470, y, "تعداد", 24, MUTED)
    c.text_r(r - 560, y, "قیمت واحد", 24, MUTED)
    c.text_l(PAD + 44, y, "جمع", 24, MUTED)
    y += 46
    for it in items:
        qty = float(it.get("qty") or 0)
        unit = float(it.get("unit_price") or 0)
        c.text_r(r, y, it.get("name") or "", 30, TEXT, max_w=410)
        if it.get("variant"):
            c.text_r(r, y + 40, f"رنگ: {it['variant']}", 24, MUTED, max_w=410)
        c.text_r(r - 470, y, fa_num(qty), 30, TEXT)
        c.text_r(r - 560, y, fa_num(unit), 28, MUTED)
        c.text_l(PAD + 44, y, fa_num(qty * unit), 30, TEXT, True)
        y += _row_h(it)
        c.rule(y - 14)
    return y


def _total_panel(c: Canvas, y: int, total, currency: str, label: str = "مبلغ قابل پرداخت") -> int:
    box = (PAD, y, W - PAD, y + 150)
    c.panel(box, fill=ACCENT + (46,), edge=ACCENT + (150,))
    c.text_r(W - PAD - 44, y + 24, label, 28, (190, 215, 255))
    right_edge = c.text_r(W - PAD - 44, y + 74, currency, 30, (190, 215, 255))
    f = _font(True, 68)
    c.d.text((right_edge - 16, y + 50), shape(fa_num(total)), font=f, fill=(255, 255, 255), anchor="ra")
    return y + 150


def _order_head(c: Canvas, y: int, title: str, number_label: str, number, date_text: str) -> int:
    c.text_r(W - PAD - 10, y, title, 54, TEXT, True)
    y += 84
    c.text_r(W - PAD - 10, y, f"{number_label} {fa_digits(number)}", 32, (190, 215, 255), True)
    c.text_l(PAD + 10, y + 4, date_text, 30, MUTED)
    return y + 56


# ---------------------------------------------------------------- pre-invoice
@_safe
def pre_invoice_card(*, shop: str, order_id, items, total, card_number: str = "",
                     card_owner: str = "", bank_name: str = "", currency: str = "ریال",
                     date=None) -> bytes | None:
    """Order number, Shamsi date, lines, total and the bank card to pay into."""
    items = list(items or [])[:10]
    has_card = any(ch.isdigit() for ch in str(card_number or ""))
    table = _table_h(items)
    height = 150 + table + 24 + 150 + 24 + (236 if has_card else 126) + 90
    c = Canvas(height)
    y = c.header(shop, "پیش‌فاکتور") + 4
    c.panel((PAD, y, W - PAD, y + table))
    yy = _order_head(c, y + 28, "پیش‌فاکتور سفارش", "شماره سفارش", order_id,
                     fa_digits(shamsi_date(date)))
    c.rule(yy + 4)
    _items_table(c, yy + 24, items, currency)
    y += table + 24
    y = _total_panel(c, y, total, currency) + 24
    if has_card:
        c.panel((PAD, y, W - PAD, y + 236))
        c.text_r(W - PAD - 44, y + 24, "پرداخت با کارت‌به‌کارت", 28, MUTED)
        # the card number is always left-to-right Latin digits: no bidi, no shaping
        digits = "".join(ch for ch in str(card_number) if ch.isdigit())
        groups = "   ".join(digits[i:i + 4] for i in range(0, len(digits), 4))
        c.d.text((W / 2, y + 66), groups, font=_font(True, 62), fill=(255, 255, 255), anchor="ma")
        c.text_r(W - PAD - 44, y + 164, f"به نام: {card_owner}", 28, TEXT, max_w=480)
        c.text_l(PAD + 44, y + 164, bank_name, 28, MUTED, max_w=360)
        y += 236
    else:
        c.panel((PAD, y, W - PAD, y + 126))
        c.text_r(W - PAD - 44, y + 40, "اطلاعات پرداخت در پیام بعدی ارسال می‌شود.", 28, TEXT)
        y += 126
    c.text_c(W / 2, y + 30, "پس از واریز، تصویر رسید را در همین گفتگو بفرستید", 24, MUTED,
             max_w=W - 2 * PAD)
    return c.png()


# -------------------------------------------------------------- final invoice
@_safe
def final_invoice_card(*, shop: str, order_id, items, total, partial: bool = False,
                       accounting_no=None, currency: str = "ریال", date=None) -> bytes | None:
    """Invoice issued in accounting. Lines/prices are the order's own (see PROGRESS)."""
    items = list(items or [])[:10]
    table = _table_h(items)
    height = 150 + table + 24 + 150 + 24 + 64 + 70
    c = Canvas(height)
    y = c.header(shop, "فاکتور") + 4
    c.panel((PAD, y, W - PAD, y + table))
    title = "فاکتور بخشی از سفارش" if partial else "فاکتور سفارش"
    yy = _order_head(c, y + 28, title, "شماره سفارش", order_id, fa_digits(shamsi_date(date)))
    if accounting_no:
        c.text_l(PAD + 10, y + 28 + 14, f"ثبت حسابداری {fa_digits(accounting_no)}", 24, MUTED)
    c.rule(yy + 4)
    _items_table(c, yy + 24, items, currency)
    y += table + 24
    y = _total_panel(c, y, total, currency, "جمع سفارش" if partial else "جمع فاکتور") + 28
    badge = "بخشی از سفارش فاکتور شد" if partial else "فاکتور صادر شد"
    f = _font(True, 26)
    s = shape(badge)
    w = int(f.getlength(s)) + 64
    c.pill((W - PAD - w, y, W - PAD, y + 54), GOOD)
    c.d.ellipse((W - PAD - w + 18, y + 20, W - PAD - w + 32, y + 34), fill=GOOD)
    c.d.text((W - PAD - w + 44, y + 10), s, font=f, fill=GOOD, anchor="la")
    c.text_l(PAD + 10, y + 12, "ارسال پس از آماده‌سازی انجام می‌شود", 24, MUTED, max_w=420)
    return c.png()
