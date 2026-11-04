"""v2.18.1 «محاسبهٔ اقساط»: the formula, the rounding helper, manual edits and the Jalali schedule.

Plain Python and nothing else, because ShopAdmin needs the same answers at every key press: this
file is copied as it is to shopadmin/app/installments.py (a test keeps them identical).

    remaining = price - down
    interest = remaining * rate% * months
    installments total = remaining + interest
    each check = installments total / months
    grand total = down + installments total

All money is whole Rials. A total that does not divide evenly leaves its few Rials on the last
check, so the checks always add up exactly.

What a customer may see is :func:`customer_view`: never the rate or the interest.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from fractions import Fraction

DEFAULT_RATE = "8"
MIN_MONTHS = 1
MAX_MONTHS = 24
#: the comparison table
COMPARE_MONTHS = tuple(range(1, 13))
MAX_AMOUNT = 1_000_000_000_000_000
#: the rounding helper; a suggestion only: nothing is rounded until the user picks one
ROUND_NONE, ROUND_EQUAL, ROUND_LAST = "none", "equal", "last"
ROUND_STEPS = (100_000, 1_000_000)

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
#: thousands separators and marks a pasted number may carry
_NOISE = str.maketrans("", "", "٬,،'’ \t‌‎‏‪‫‬ ")


def parse_amount(text: object) -> int | None:
    """Persian or English digits, with or without thousands separators; None when not a whole
    number that is zero or more."""
    value = str(text if text is not None else "").translate(_DIGITS).translate(_NOISE)
    for unit in ("ریال", "ريال"):
        value = value.replace(unit, "")
    return int(value) if value.isascii() and value.isdigit() else None


def parse_rate(text: object) -> Fraction | None:
    """«۸»، «8.5»، «۸٫۵»، «۸٪»: the monthly rate in percent, or None."""
    value = str(text if text is not None else "").translate(_DIGITS).strip()
    value = value.replace("٫", ".").replace("/", ".").rstrip("%٪").strip()
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return rate if 0 <= rate <= 100 else None


def parse_down(text: object, price: int | None = None) -> int | None:
    """The down payment as an amount, or as a percent of the price («۵۰٪»)."""
    value = str(text if text is not None else "").translate(_DIGITS).strip()
    if value.endswith(("%", "٪")):
        rate = parse_rate(value)
        return None if rate is None or price is None else _round(price * rate / 100)
    return parse_amount(value)


def _round(value: Fraction | int) -> int:
    """Half up, without the surprises of a float."""
    return int((Fraction(value) + Fraction(1, 2)).__floor__())


def _ceil_to(value: Fraction | int, step: int) -> int:
    whole = Fraction(value) / step
    return int(-((-whole).__floor__())) * step


def _floor_to(value: Fraction | int, step: int) -> int:
    return int((Fraction(value) / step).__floor__()) * step


def rate_text(rate: object) -> str:
    """The rate as it was typed: «8» or «8.5»."""
    value = parse_rate(rate)
    if value is None:
        return str(rate)
    if value.denominator == 1:
        return str(value.numerator)
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def problem(price: object, down: object, months: object, rate: object = DEFAULT_RATE) -> str:
    """The first thing wrong with these inputs, as a Persian sentence, or ''."""
    if not isinstance(price, int) or price <= 0:
        return "قیمت گوشی را بنویسید."
    if price > MAX_AMOUNT:
        return "قیمت گوشی بیش از اندازه است."
    if not isinstance(down, int) or down < 0:
        return "پیش‌پرداخت درست نیست."
    if down >= price:
        return "پیش‌پرداخت باید کمتر از قیمت گوشی باشد."
    if not isinstance(months, int) or isinstance(months, bool) or months < MIN_MONTHS:
        return "تعداد ماه باید دست‌کم ۱ باشد."
    if months > MAX_MONTHS:
        return "تعداد ماه حداکثر ۲۴ است."
    if parse_rate(rate) is None:
        return "نرخ ماهانه درست نیست."
    return ""


@dataclass(frozen=True)
class Quote:
    price: int
    down: int
    months: int
    rate: str
    remaining: int
    interest: int
    installments_total: int
    each_check: int
    checks: tuple[int, ...]
    grand_total: int

    def as_dict(self) -> dict:
        out = asdict(self)
        out["checks"] = list(self.checks)
        return out


def _spread(total: int, months: int) -> list[int]:
    each = total // months
    return [each] * (months - 1) + [total - each * (months - 1)]


def calculate(price: int, down: int, months: int, rate: object = DEFAULT_RATE) -> Quote:
    """Raises ValueError with the Persian sentence of :func:`problem`."""
    wrong = problem(price, down, months, rate)
    if wrong:
        raise ValueError(wrong)
    remaining = price - down
    interest = _round(remaining * parse_rate(rate) * months / 100)
    total = remaining + interest
    checks = _spread(total, months)
    return Quote(price=price, down=down, months=months, rate=rate_text(rate), remaining=remaining,
                 interest=interest, installments_total=total, each_check=checks[0],
                 checks=tuple(checks), grand_total=down + total)


@dataclass(frozen=True)
class Rounded:
    mode: str
    step: int
    checks: tuple[int, ...]
    #: what the shop gets above the calculation (goes to interest)
    extra: int
    interest: int
    installments_total: int
    grand_total: int


def rounded(quote: Quote, mode: str = ROUND_NONE, step: int = 0) -> Rounded:
    """A suggestion:

    * ``none``: as calculated;
    * ``equal``: each check UP to ``step``, all equal; the extra goes to interest;
    * ``last``: each check UP to ``step``, the last takes the difference (the total stays). When
      that would leave nothing for the last check, each is rounded DOWN instead.
    """
    total, months = quote.installments_total, quote.months
    if mode == ROUND_EQUAL and step > 0:
        checks = [_ceil_to(Fraction(total, months), step)] * months
    elif mode == ROUND_LAST and step > 0:
        each = _ceil_to(Fraction(total, months), step)
        if months > 1 and total - each * (months - 1) <= 0:
            each = _floor_to(Fraction(total, months), step)
        checks = [each] * (months - 1) + [total - each * (months - 1)]
    else:
        mode, step, checks = ROUND_NONE, 0, list(quote.checks)
    new_total = sum(checks)
    return Rounded(mode=mode, step=step, checks=tuple(checks), extra=new_total - total,
                   interest=quote.interest + new_total - total, installments_total=new_total,
                   grand_total=quote.down + new_total)


@dataclass(frozen=True)
class Totals:
    """What a set of (possibly hand-edited) amounts adds up to, against the calculation."""
    down: int
    checks: tuple[int, ...]
    installments_total: int
    grand_total: int
    interest: int
    #: grand total minus the calculated grand total (+ = more than calculated)
    difference: int


def totals(quote: Quote, down: int, checks: list[int] | tuple[int, ...]) -> Totals:
    """Live recalculation after a manual edit. The interest is whatever is above the price."""
    installments = sum(checks)
    grand = down + installments
    return Totals(down=down, checks=tuple(checks), installments_total=installments,
                  grand_total=grand, interest=grand - quote.price,
                  difference=grand - quote.grand_total)


def edit_problem(price: int, down: int, checks: list[int] | tuple[int, ...]) -> str:
    """Hand-edited amounts that cannot be right, as a Persian sentence, or ''."""
    if down < 0:
        return "پیش‌پرداخت درست نیست."
    if down >= price:
        return "پیش‌پرداخت باید کمتر از قیمت گوشی باشد."
    if not checks:
        return "دست‌کم یک چک لازم است."
    if any(amount <= 0 for amount in checks):
        return "مبلغ هر چک باید بیشتر از صفر باشد."
    return ""


def with_total(checks: list[int], wanted: int) -> list[int]:
    """A typed total of the checks: the last check takes the difference. Unchanged when that
    would leave it at zero or less."""
    last = wanted - sum(checks[:-1])
    return checks if not checks or last <= 0 else [*checks[:-1], last]


def comparison(price: int, down: int, rate: object = DEFAULT_RATE,
               months: tuple[int, ...] = COMPARE_MONTHS) -> list[Quote]:
    return [calculate(price, down, m, rate) for m in months]


# ---- the Jalali calendar ---------------------------------------------------------------------
def jalali_from_date(day) -> tuple[int, int, int]:
    """A ``datetime.date`` as (year, month, day) of the Jalali calendar."""
    year, month, dom = day.year, day.month, day.day
    table = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = year + 1 if month > 2 else year
    days = (355666 + 365 * year + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
            + dom + table[month - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def is_leap(jy: int) -> bool:
    return ((jy + 12) % 33) % 4 == 1


def month_length(jy: int, jm: int) -> int:
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_leap(jy) else 29


def parse_jalali(text: object) -> tuple[int, int, int] | None:
    """«۱۴۰۵/۰۹/۱۵» or 1405-9-15; None when it is not a real day."""
    value = str(text or "").translate(_DIGITS).replace("-", "/").strip()
    parts = value.split("/")
    if len(parts) != 3 or not all(part.isascii() and part.isdigit() for part in parts):
        return None
    jy, jm, jd = (int(part) for part in parts)
    if not (1300 <= jy <= 1600 and 1 <= jm <= 12 and 1 <= jd <= month_length(jy, jm)):
        return None
    return jy, jm, jd


def jalali_text(jy: int, jm: int, jd: int) -> str:
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def add_months(jy: int, jm: int, jd: int, count: int) -> tuple[int, int, int]:
    """Same day of a later month; the 31st of a shorter month is its last day."""
    index = jy * 12 + (jm - 1) + count
    year, month = index // 12, index % 12 + 1
    return year, month, min(jd, month_length(year, month))


def schedule(first: object, months: int) -> list[str]:
    """The due date of each check, one month apart. [] without a real first date."""
    start = parse_jalali(first)
    if start is None:
        return []
    return [jalali_text(*add_months(*start, i)) for i in range(months)]


# ---- what a customer may see -----------------------------------------------------------------
@dataclass(frozen=True)
class CheckGroup:
    count: int
    amount: int


def check_groups(checks: list[int] | tuple[int, ...]) -> list[CheckGroup]:
    """«۴ چک × ۲۸٬۰۰۰٬۰۰۰» and «۱ چک × ۲۸٬۰۰۰٬۰۰۱»: runs of the same amount, in order."""
    out: list[CheckGroup] = []
    for amount in checks:
        if out and out[-1].amount == amount:
            out[-1] = CheckGroup(out[-1].count + 1, amount)
        else:
            out.append(CheckGroup(1, amount))
    return out


def fa_money(value: int) -> str:
    return f"{int(value):,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))


def fa_text(value: object) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


@dataclass(frozen=True)
class Sheet:
    """A quote as it was finally agreed: the calculation plus any manual edits."""
    phone_name: str
    price: int
    down: int
    rate: str
    checks: tuple[int, ...]
    dates: tuple[str, ...] = field(default_factory=tuple)
    #: the quote's own date (Jalali)
    date: str = ""

    @property
    def grand_total(self) -> int:
        return self.down + sum(self.checks)

    @property
    def interest(self) -> int:
        return self.grand_total - self.price


def sheet_problem(sheet: Sheet) -> str:
    wrong = edit_problem(sheet.price, sheet.down, sheet.checks)
    if wrong:
        return wrong
    if not MIN_MONTHS <= len(sheet.checks) <= MAX_MONTHS:
        return "تعداد چک باید بین ۱ و ۲۴ باشد."
    if sheet.dates and len(sheet.dates) != len(sheet.checks):
        return "تاریخ هر چک لازم است."
    if any(parse_jalali(day) is None for day in sheet.dates):
        return "تاریخ چک درست نیست."
    if sheet.price > MAX_AMOUNT or sheet.grand_total > MAX_AMOUNT:
        return "مبلغ بیش از اندازه است."
    return ""


def customer_view(sheet: Sheet) -> dict:
    """The only thing that goes to a customer or a bot: no rate, no interest and no cash price
    (the two together would give the interest away)."""
    return {
        "phone_name": sheet.phone_name, "down": sheet.down,
        "check_count": len(sheet.checks), "checks": list(sheet.checks),
        "groups": [{"count": g.count, "amount": g.amount} for g in check_groups(sheet.checks)],
        "dates": list(sheet.dates), "grand_total": sheet.grand_total, "date": sheet.date,
    }


def customer_text(sheet: Sheet, shop: str = "") -> str:
    """The text of the card, for «کپی متن» and when no image can be made."""
    lines = [f"🧾 پیشنهاد اقساط{f' — {shop}' if shop else ''}"]
    if sheet.phone_name:
        lines.append(f"گوشی: {sheet.phone_name}")
    lines.append(f"نقد (پیش‌پرداخت): {fa_money(sheet.down)} ریال")
    for group in check_groups(sheet.checks):
        lines.append(f"{fa_text(group.count)} چک × {fa_money(group.amount)} ریال")
    if sheet.dates:
        lines.append(f"تاریخ اولین چک: {fa_text(sheet.dates[0])}")
    lines.append(f"جمع کل: {fa_money(sheet.grand_total)} ریال")
    if sheet.date:
        lines.append(f"تاریخ: {fa_text(sheet.date)}")
    return "\n".join(lines)


def staff_text(sheet: Sheet, base: Quote | None = None) -> str:
    """Everything, for staff only: with the rate and the interest."""
    lines = [customer_text(sheet), f"قیمت نقدی گوشی: {fa_money(sheet.price)} ریال",
             f"نرخ ماهانه: {fa_text(sheet.rate)}٪", f"سود: {fa_money(sheet.interest)} ریال"]
    for number, amount in enumerate(sheet.checks, 1):
        day = sheet.dates[number - 1] if number <= len(sheet.dates) else ""
        lines.append(f"چک {fa_text(number)}: {fa_money(amount)} ریال"
                     + (f" — {fa_text(day)}" if day else ""))
    if base is not None and sheet.grand_total != base.grand_total:
        lines.append("اختلاف با محاسبه: " + difference_text(sheet.grand_total - base.grand_total))
    return "\n".join(lines)


def difference_text(difference: int) -> str:
    if not difference:
        return "بدون اختلاف"
    # in words: a sign lands on the wrong side of a number in a right-to-left line
    return f"{fa_money(abs(difference))} ریال {'بیشتر' if difference > 0 else 'کمتر'}"
