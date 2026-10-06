"""Price level per channel and availability math (pure functions)."""
import pytest

from app.accounting_reader import (
    FORBIDDEN_PRICE_COLUMNS,
    PRICE_COLUMNS,
    compute_available,
    price_column,
)
from app.config import Settings


def test_price_column_mapping():
    assert price_column(1) == "Gey"
    assert price_column(2) == "Geycf"
    assert price_column(3) == "gey3"
    assert price_column(4) == "gey4"
    assert price_column(5) == "gey5"


def test_invalid_price_level():
    with pytest.raises(ValueError):
        price_column(9)


def test_geya_geyk_geym_never_exposed():
    for col in FORBIDDEN_PRICE_COLUMNS:
        assert col not in PRICE_COLUMNS.values()


def test_channel_price_level_defaults():
    s = Settings()
    assert s.price_level_for("bot") == 3
    assert s.price_level_for("site") == 3


def test_channel_price_level_override():
    s = Settings(price_level_bot=3, price_level_site=5)
    assert s.price_level_for("bot") == 3
    assert s.price_level_for("site") == 5
    assert price_column(s.price_level_for("site")) == "gey5"


def test_availability_formula():
    assert compute_available(10, 3, 2) == 5
    assert compute_available(0, 0, 0) == 0
    assert compute_available(5, 0, 0) == 5
    assert compute_available(5, 6, 0) == 0  # over-reserved clamps to 0, never negative
