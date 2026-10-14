"""Account statement (گردش حساب) as ONE A4 PDF document (v2.6.0).

Same toolchain as the image cards (``render.py``): an HTML page with the embedded
Vazirmatn font, printed by the headless Chromium/Edge that is already used for the
cards (``--print-to-pdf``). The browser does the Persian shaping, RTL and the page
breaks; the table header repeats on every page. No extra Python dependency.

Content: header (shop logo + name, customer name and code, date range, print
date), a table (date, description, debit, credit, running balance + side),
the totals and the final balance in bold (بدهکار / بستانکار / تسویه).
Dates are the accounting software's Jalali dates; the print date is Jalali too.

``statement_pdf`` returns PDF bytes, or None when anything fails (no browser,
timeout, bad output) - the bot then sends the paged text statement instead.
"""
from __future__ import annotations

import datetime as _dt
import logging
import subprocess

from .jdate import shamsi_date
from .render import (
    FONT_BOLD,
    FONT_REGULAR,
    RENDER_TIMEOUT,
    OUTPUT_WAIT,
    _font_b64,
    _logo_html,
    _wait_for_file,
    _work_dir,
    esc,
    fa_digits,
    fa_num,
    find_browser,
)

logger = logging.getLogger("shopbots.cards")

SIDES = {"debtor": "بدهکار", "creditor": "بستانکار", "zero": "تسویه"}
SIDE_SHORT = {"debtor": "بد", "creditor": "بس", "zero": "—"}

_CSS = """
@page{size:A4;margin:12mm 11mm 14mm}
@font-face{font-family:'Vazirmatn';font-weight:400;src:url(data:font/ttf;base64,__FR__) format('truetype')}
@font-face{font-family:'Vazirmatn';font-weight:700;src:url(data:font/ttf;base64,__FB__) format('truetype')}
*{box-sizing:border-box;margin:0;padding:0}
html,body{font-family:'Vazirmatn',sans-serif;direction:rtl;color:#0d2a55;font-size:10.5pt;line-height:1.55;
  -webkit-print-color-adjust:exact;print-color-adjust:exact}
.head{display:flex;align-items:center;gap:14px;border-bottom:2px solid #0b3d86;padding-bottom:8px;margin-bottom:10px}
.head .logo{height:60px;max-width:150px;object-fit:contain}
.head .t{flex:1}
.head h1{font-size:17pt;color:#0b3d86;line-height:1.3}
.head h2{font-size:12pt;font-weight:700;color:#1d6fd6}
.info{display:grid;grid-template-columns:1fr 1fr;gap:4px 18px;border:1.5px solid #9cc3ee;border-radius:10px;
  background:#eaf3fd;padding:8px 14px;margin-bottom:12px}
.info div{display:flex;gap:8px}.info b{color:#0b3d86;min-width:92px}
table{width:100%;border-collapse:collapse;table-layout:fixed}
thead{display:table-header-group}tfoot{display:table-row-group}
tr{page-break-inside:avoid;break-inside:avoid}
th{background:#0b3d86;color:#fff;font-weight:700;padding:5px 6px;font-size:10pt;border:1px solid #0b3d86}
td{padding:4px 6px;border:1px solid #c8dcf4;vertical-align:top}
tbody tr:nth-child(even) td{background:#f4f8fe}
td.n{text-align:center;white-space:nowrap}
td.d{text-align:center;white-space:nowrap;width:78px}
td.s{text-align:center;white-space:nowrap}
td.desc{word-wrap:break-word;overflow-wrap:anywhere}
tr.open td{background:#fff8e6 !important;font-style:italic}
tfoot td{font-weight:700;background:#dbe9fa;border-color:#9cc3ee}
.final{margin-top:12px;border:2px solid #0b3d86;border-radius:10px;padding:10px 14px;display:flex;
  justify-content:space-between;align-items:center;font-size:13pt;font-weight:700;color:#0b3d86;break-inside:avoid}
.final .v{font-size:15pt}
.final .debtor{color:#b42318}.final .creditor{color:#0f7a52}
.note{margin-top:8px;font-size:9pt;color:#4f6a8f}
.foot{margin-top:14px;padding-top:6px;border-top:1px solid #9cc3ee;font-size:9pt;color:#4f6a8f;text-align:center}
"""


def _row(cells: list[tuple[str, str]], cls: str = "") -> str:
    tds = "".join(f'<td class="{c}">{v}</td>' for c, v in cells)
    return f'<tr class="{cls}">{tds}</tr>' if cls else f"<tr>{tds}</tr>"


def statement_html(data: dict, *, shop: str, currency: str = "ریال", contact: dict | None = None,
                   printed: _dt.datetime | None = None, title: str = "صورت‌حساب (گردش حساب)") -> str:
    printed = printed or _dt.datetime.now()
    rows = [r for r in (data.get("rows") or []) if isinstance(r, dict)]
    body_rows: list[str] = []
    opening = float(data.get("opening_balance") or 0)
    if opening >= 0.5:
        side = str(data.get("opening_side") or "zero")
        body_rows.append(_row([
            ("d", ""), ("desc", "مانده از قبل"), ("n", ""), ("n", ""),
            ("n", fa_num(opening)), ("s", SIDE_SHORT.get(side, "")),
        ], "open"))
    for r in rows:
        parts = [str(r.get("kind") or "").strip()]
        if r.get("doc_no"):
            parts.append(f"شمارهٔ {fa_digits(r['doc_no'])}")
        if r.get("description"):
            parts.append("— " + str(r["description"]).strip())
        debit, credit = float(r.get("debit") or 0), float(r.get("credit") or 0)
        side = str(r.get("side") or "zero")
        body_rows.append(_row([
            ("d", esc(fa_digits(r.get("date") or ""))),
            ("desc", esc(" ".join(p for p in parts if p))),
            ("n", fa_num(debit) if debit else ""),
            ("n", fa_num(credit) if credit else ""),
            ("n", fa_num(r.get("balance") or 0)),
            ("s", SIDE_SHORT.get(side, "")),
        ]))
    if not body_rows:
        body_rows.append(_row([("d", ""), ("desc", "گردشی ثبت نشده است."), ("n", ""), ("n", ""),
                               ("n", ""), ("s", "")]))
    side = str(data.get("side") or "zero")
    balance = float(data.get("balance") or 0)
    date_from = fa_digits(data.get("from_date") or "—")
    date_to = fa_digits(data.get("to_date") or "—")
    stamp = f"{fa_digits(shamsi_date(printed))} — {fa_digits(printed.strftime('%H:%M'))}"
    name = esc(data.get("customer_name") or "—")
    code = esc(fa_digits(data.get("person_code") or "—"))
    truncated = ('<p class="note">فقط جدیدترین گردش‌ها آمده است؛ ماندهٔ گردش‌های قدیمی‌تر در ردیف '
                 '«مانده از قبل» منظور شده است.</p>') if data.get("truncated") else ""
    contact = contact or {}
    foot_bits = [f"<bdi>{esc(v)}</bdi>" for v in (contact.get("address"), contact.get("phone"),
                                                 contact.get("bot_id")) if v]
    foot = f'<div class="foot">{" | ".join(foot_bits)}</div>' if foot_bits else ""
    css = _CSS.replace("__FR__", _font_b64(FONT_REGULAR)).replace("__FB__", _font_b64(FONT_BOLD))
    return (
        f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>{css}</style>'
        f'<title>{esc(title)}</title></head><body>'
        f'<div class="head">{_logo_html()}<div class="t"><h1>{esc(shop)}</h1>'
        f'<h2>{esc(title)}</h2></div></div>'
        f'<div class="info"><div><b>نام مشتری:</b><span>{name}</span></div>'
        f'<div><b>کد مشتری:</b><span>{code}</span></div>'
        f'<div><b>از تاریخ:</b><span>{date_from}</span></div>'
        f'<div><b>تا تاریخ:</b><span>{date_to}</span></div>'
        f'<div><b>تاریخ چاپ:</b><span>{stamp}</span></div>'
        f'<div><b>واحد مبالغ:</b><span>{esc(currency)}</span></div></div>'
        '<table><colgroup><col style="width:13%"><col style="width:35%"><col style="width:14%">'
        '<col style="width:14%"><col style="width:15%"><col style="width:9%"></colgroup>'
        '<thead><tr><th>تاریخ</th><th>شرح</th><th>بدهکار</th><th>بستانکار</th><th>مانده</th>'
        '<th>تشخیص</th></tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody>'
        f'<tfoot><tr><td></td><td>جمع</td><td class="n">{fa_num(data.get("total_debit") or 0)}</td>'
        f'<td class="n">{fa_num(data.get("total_credit") or 0)}</td><td></td><td></td></tr></tfoot>'
        '</table>'
        f'<div class="final"><span>ماندهٔ نهایی حساب</span><span class="v {esc(side)}">'
        f'{fa_num(balance)} {esc(currency)} — {SIDES.get(side, "")}</span></div>'
        f'{truncated}{foot}</body></html>'
    )


def _print_pdf(page_html: str) -> bytes | None:
    browser = find_browser()
    if not browser:
        logger.warning("statement pdf: no Chromium/Edge found (set BOT_CARD_BROWSER) - text fallback")
        return None
    with _work_dir() as tmpd:
        page = tmpd / "statement.html"
        out = tmpd / "statement.pdf"
        page.write_text(page_html, encoding="utf-8")
        cmd = [
            browser, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
            "--disable-extensions", "--disable-background-networking",
            "--no-pdf-header-footer", "--print-to-pdf-no-header",
            "--virtual-time-budget=3000", f"--user-data-dir={tmpd / 'profile'}",
            f"--print-to-pdf={out}", page.as_uri(),
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(cmd, check=False, timeout=RENDER_TIMEOUT, creationflags=flags,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            logger.warning("statement pdf: browser timed out - text fallback")
            return None
        if not _wait_for_file(out, OUTPUT_WAIT):
            logger.warning("statement pdf: browser produced no file - text fallback")
            return None
        data = out.read_bytes()
    return data if data.startswith(b"%PDF") else None


def statement_pdf(data: dict, *, shop: str, currency: str = "ریال",
                  contact: dict | None = None, printed: _dt.datetime | None = None) -> bytes | None:
    try:
        return _print_pdf(statement_html(data, shop=shop, currency=currency, contact=contact,
                                         printed=printed))
    except Exception as exc:  # noqa: BLE001 - the text statement is the fallback
        logger.warning("statement pdf failed: %s", type(exc).__name__)
        return None
