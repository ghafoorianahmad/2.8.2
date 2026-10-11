"""Phone pricing rules (REQUIREMENTS §4). All results are Rial.

* customer price = «روال» unchanged;
* «روال» empty -> «نقد» + 500,000 Toman (5,000,000 Rial);
* both empty / "..." -> None (unavailable; inquiry only).

PDF prices are thousand Toman: ×10,000 = Rial (``52,500`` -> 525,000,000).
"""
from __future__ import annotations

UNIT_RIAL = 10_000
CASH_SURCHARGE_RIAL = 5_000_000


def customer_price_rial(
    naghd: int | None,
    raval: int | None,
    *,
    unit_rial: int = UNIT_RIAL,
    cash_surcharge_rial: int = CASH_SURCHARGE_RIAL,
) -> int | None:
    if raval is not None and raval > 0:
        return int(raval) * unit_rial
    if naghd is not None and naghd > 0:
        return int(naghd) * unit_rial + cash_surcharge_rial
    return None


def change_pct(old: int | None, new: int | None) -> float | None:
    """Relative change in percent, or None when either side has no price."""
    if not old or not new:
        return None
    return abs(new - old) * 100.0 / old
