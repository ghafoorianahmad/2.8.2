from datetime import date

from app.ui.pages.dashboard import orders_per_day


def test_orders_per_day_buckets_last_seven_days():
    today = date(2026, 10, 7)
    orders = [
        {"created_at": "2026-10-07T09:00:00"},
        {"created_at": "2026-10-07T11:00:00"},
        {"created_at": "2026-10-01T09:00:00"},
        {"created_at": "2026-09-01T09:00:00"},  # outside the window
        {"created_at": None},
    ]
    data = orders_per_day(orders, today=today)
    assert len(data) == 7
    assert [count for _, count in data] == [1, 0, 0, 0, 0, 0, 2]
