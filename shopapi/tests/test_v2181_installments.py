"""v2.18.1 item 17: the formula, the rounding helper, manual edits, the schedule, the customer view
and the endpoints."""
from __future__ import annotations

import base64
from datetime import date
from pathlib import Path

import pytest

from app import installment_card, installments as inst

from .conftest import h, register_and_approve, seed_products
from .test_phase3 import staff

EXAMPLE = {"price": 200_000_000, "down": 100_000_000, "months": 5, "rate": "8"}


# ---- the formula -------------------------------------------------------------------------------
def test_the_owners_example():
    quote = inst.calculate(**EXAMPLE)
    assert quote.remaining == 100_000_000
    assert quote.interest == 40_000_000
    assert quote.installments_total == 140_000_000
    assert quote.each_check == 28_000_000 and quote.checks == (28_000_000,) * 5
    assert quote.grand_total == 240_000_000


def test_one_month():
    quote = inst.calculate(100, 0, 1, "10")
    assert quote.interest == 10 and quote.checks == (110,) and quote.grand_total == 110


def test_zero_rate():
    quote = inst.calculate(1_000_000, 100_000, 3, "0")
    assert quote.interest == 0 and quote.grand_total == 1_000_000
    assert quote.checks == (300_000, 300_000, 300_000)


def test_a_total_that_does_not_divide_stays_exact():
    quote = inst.calculate(1_000_000, 0, 3, "1")
    assert quote.installments_total == 1_030_000
    assert sum(quote.checks) == quote.installments_total
    assert quote.checks[:2] == (343_333, 343_333) and quote.checks[2] == 343_334


def test_a_fractional_rate_is_exact_not_a_float():
    assert inst.calculate(100_000_000, 0, 3, "8.5").interest == 25_500_000
    assert inst.calculate(100_000_000, 0, 3, "۸٫۵").interest == 25_500_000
    # 0.1 + 0.2 style errors would miss this
    assert inst.calculate(300_000_000, 0, 1, "0.1").interest == 300_000


def test_half_a_rial_rounds_up():
    assert inst.calculate(5, 0, 1, "10").interest == 1
    assert inst.calculate(4, 0, 1, "10").interest == 0


@pytest.mark.parametrize("args,word", [
    ((0, 0, 5), "قیمت"), ((-1, 0, 5), "قیمت"),
    ((100, 100, 5), "کمتر"), ((100, 200, 5), "کمتر"), ((100, -1, 5), "پیش‌پرداخت"),
    ((100, 0, 0), "ماه"), ((100, 0, 25), "۲۴"),
])
def test_validation(args, word):
    assert word in inst.problem(*args)
    with pytest.raises(ValueError):
        inst.calculate(*args)


def test_a_bad_rate_is_refused():
    assert inst.problem(100, 0, 1, "abc") and inst.problem(100, 0, 1, "101")


# ---- digits and separators ---------------------------------------------------------------------
@pytest.mark.parametrize("text,value", [
    ("200,000,000", 200_000_000), ("۲۰۰٬۰۰۰٬۰۰۰", 200_000_000), ("٢٠٠٠", 2000),
    ("1 000", 1000), ("۱۲۳ریال", 123), ("0", 0), ("‎500", 500),
])
def test_amounts(text, value):
    assert inst.parse_amount(text) == value


@pytest.mark.parametrize("text", ["", "abc", "12.5", "-5", "۱۲a", None])
def test_not_amounts(text):
    assert inst.parse_amount(text) is None


def test_the_down_payment_as_a_percent():
    assert inst.parse_down("۵۰٪", 200_000_000) == 100_000_000
    assert inst.parse_down("25%", 200_000_000) == 50_000_000
    assert inst.parse_down("100,000,000", 200_000_000) == 100_000_000
    assert inst.parse_down("50%", None) is None


# ---- rounding (a suggestion) --------------------------------------------------------------------
def _odd():
    return inst.calculate(100_000_000, 0, 3, "8.33")  # 124,990,000 -> 41,663,333.33


def test_no_rounding_is_the_calculation():
    quote = _odd()
    result = inst.rounded(quote)
    assert result.checks == quote.checks and result.extra == 0


def test_equal_rounds_every_check_up_and_the_extra_is_interest():
    quote = _odd()
    result = inst.rounded(quote, inst.ROUND_EQUAL, 100_000)
    assert set(result.checks) == {41_700_000}
    assert result.extra == 41_700_000 * 3 - quote.installments_total > 0
    assert result.interest == quote.interest + result.extra
    assert result.grand_total == quote.grand_total + result.extra


def test_equal_to_a_million():
    result = inst.rounded(_odd(), inst.ROUND_EQUAL, 1_000_000)
    assert set(result.checks) == {42_000_000}


def test_last_takes_the_difference_and_the_total_stays():
    quote = _odd()
    result = inst.rounded(quote, inst.ROUND_LAST, 100_000)
    assert result.checks[:2] == (41_700_000, 41_700_000)
    assert sum(result.checks) == quote.installments_total
    assert result.extra == 0 and result.grand_total == quote.grand_total


def test_last_never_leaves_the_last_check_empty():
    quote = inst.calculate(1_100_000, 0, 12, "0")
    result = inst.rounded(quote, inst.ROUND_LAST, 1_000_000)
    assert sum(result.checks) == quote.installments_total and result.checks[-1] > 0


def test_an_even_amount_is_not_moved():
    quote = inst.calculate(**EXAMPLE)
    assert inst.rounded(quote, inst.ROUND_EQUAL, 1_000_000).checks == quote.checks
    assert inst.rounded(quote, inst.ROUND_EQUAL, 1_000_000).extra == 0


# ---- manual edits -------------------------------------------------------------------------------
def test_a_changed_check_changes_the_totals_and_the_difference():
    quote = inst.calculate(**EXAMPLE)
    checks = list(quote.checks)
    checks[0] += 1_000_000
    result = inst.totals(quote, quote.down, checks)
    assert result.installments_total == 141_000_000
    assert result.grand_total == 241_000_000
    assert result.interest == 41_000_000
    assert result.difference == 1_000_000


def test_a_changed_down_payment_changes_them_too():
    quote = inst.calculate(**EXAMPLE)
    result = inst.totals(quote, 90_000_000, quote.checks)
    assert result.grand_total == 230_000_000 and result.difference == -10_000_000


def test_no_edit_no_difference():
    quote = inst.calculate(**EXAMPLE)
    assert inst.totals(quote, quote.down, quote.checks).difference == 0
    assert inst.difference_text(0) == "بدون اختلاف"
    assert inst.difference_text(1000) == "۱٬۰۰۰ ریال بیشتر"
    assert inst.difference_text(-1000) == "۱٬۰۰۰ ریال کمتر"


def test_a_typed_total_goes_on_the_last_check():
    assert inst.with_total([28, 28, 28], 90) == [28, 28, 34]
    assert inst.with_total([28, 28, 28], 50) == [28, 28, 28]   # nothing left for it: unchanged


@pytest.mark.parametrize("down,checks,word", [
    (-1, [10], "پیش‌پرداخت"), (100, [10], "کمتر"), (0, [], "چک"), (0, [10, 0], "صفر"),
])
def test_edits_that_cannot_be_right(down, checks, word):
    assert word in inst.edit_problem(100, down, checks)


def test_the_comparison_keeps_the_down_payment():
    rows = inst.comparison(200_000_000, 100_000_000, "8")
    assert [r.months for r in rows] == list(range(1, 13))
    assert all(r.down == 100_000_000 for r in rows)
    assert rows[4] == inst.calculate(**EXAMPLE)


# ---- the Jalali schedule ------------------------------------------------------------------------
def test_the_schedule_is_a_month_apart():
    assert inst.schedule("1405/09/15", 3) == ["1405/09/15", "1405/10/15", "1405/11/15"]


def test_the_31st_of_a_shorter_month_is_its_last_day():
    assert inst.schedule("1405/06/31", 2) == ["1405/06/31", "1405/07/30"]
    # 1403 is a leap year (Esfand 30), 1404 is not
    assert inst.add_months(1403, 11, 30, 1) == (1403, 12, 30)
    assert inst.add_months(1404, 11, 30, 1) == (1404, 12, 29)


def test_the_year_rolls_over():
    assert inst.add_months(1405, 12, 1, 1) == (1406, 1, 1)
    assert inst.add_months(1405, 1, 1, 24) == (1407, 1, 1)


def test_persian_digits_and_a_bad_date():
    assert inst.parse_jalali("۱۴۰۵/۰۹/۱۵") == (1405, 9, 15)
    assert inst.parse_jalali("1405/13/01") is None
    assert inst.parse_jalali("1405/07/31") is None
    assert inst.schedule("nonsense", 3) == []


def test_today_in_jalali():
    assert inst.jalali_from_date(date(2026, 11, 4)) == (1405, 8, 13)
    assert inst.jalali_from_date(date(2025, 3, 21)) == (1404, 1, 1)


# ---- what a customer sees ------------------------------------------------------------------------
def _sheet(**changes) -> inst.Sheet:
    quote = inst.calculate(**EXAMPLE)
    values = dict(phone_name="Galaxy S25", price=quote.price, down=quote.down, rate=quote.rate,
                  checks=quote.checks, dates=tuple(inst.schedule("1405/09/15", 5)),
                  date="1405/08/13")
    values.update(changes)
    return inst.Sheet(**values)


def test_the_customer_view_has_no_rate_or_interest_or_cash_price():
    view = inst.customer_view(_sheet(price=190_000_000))   # interest 50,000,000
    assert not {"rate", "interest", "price", "remaining"} & set(view)
    assert view["grand_total"] == 240_000_000 and view["check_count"] == 5
    assert view["groups"] == [{"count": 5, "amount": 28_000_000}]
    assert "190000000" not in str(view) and "50000000" not in str(view)


def test_the_customer_text_says_nothing_of_the_interest():
    text = inst.customer_text(_sheet(price=190_000_000), "فروشگاه")
    assert "۲۸٬۰۰۰٬۰۰۰" in text and "۲۴۰٬۰۰۰٬۰۰۰" in text and "چک ۵" in text
    assert "سود" not in text and "نرخ" not in text and "۵۰٬۰۰۰٬۰۰۰" not in text
    assert "۱۹۰٬۰۰۰٬۰۰۰" not in text


def test_the_staff_text_says_everything():
    text = inst.staff_text(_sheet())
    assert "۴۰٬۰۰۰٬۰۰۰" in text and "نرخ" in text and "۲۰۰٬۰۰۰٬۰۰۰" in text


def test_groups_follow_edited_checks():
    assert inst.check_groups((5, 5, 7)) == [inst.CheckGroup(2, 5), inst.CheckGroup(1, 7)]


def test_the_card_page_shows_no_rate_or_interest():
    page = installment_card.card_html(inst.customer_view(_sheet(price=190_000_000)),
                                      phone="09155000432")
    head, body = page.split("</style>", 1)
    assert "سود" not in body and "نرخ" not in body and "۵۰٬۰۰۰٬۰۰۰" not in body
    assert "Galaxy S25" in body and "۲۴۰٬۰۰۰٬۰۰۰" in body


def test_the_card_escapes_a_name():
    page = installment_card.card_html(inst.customer_view(_sheet(phone_name="<script>x</script>")))
    assert "<script>x" not in page


def test_no_browser_means_no_image_not_an_error(monkeypatch):
    monkeypatch.setattr(installment_card, "find_browser", lambda: None)
    assert installment_card.render_png(inst.customer_view(_sheet())) is None


def test_the_copy_in_shopadmin_is_identical():
    here = Path(__file__).resolve().parents[1] / "app" / "installments.py"
    there = Path(__file__).resolve().parents[2] / "shopadmin" / "app" / "installments.py"
    assert here.read_bytes().replace(b"\r\n", b"\n") == there.read_bytes().replace(b"\r\n", b"\n")


# ---- the endpoints -------------------------------------------------------------------------------
SHEET = {"phone_name": "Galaxy S25", "price": 200_000_000, "down": 100_000_000, "rate": "8",
         "checks": [28_000_000] * 5, "dates": inst.schedule("1405/09/15", 5)}


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch):
    """Tests make no image; test_card_when_a_browser_works says what happens when one is made."""
    monkeypatch.setattr(installment_card, "render_png", lambda *a, **k: None)


def _sales(db, ticks: str) -> dict:
    headers = staff(db, "operator", "mina")
    db._conn.execute("UPDATE staff_users SET perm_grant=? WHERE username='mina'", (ticks,))
    db._conn.commit()
    return headers


def test_the_default_rate_is_8_and_the_customer_switch_is_off(client, db):
    boss = staff(db, "super_admin", "boss")
    answer = client.get("/admin/installments/settings", headers=boss).json()
    assert answer == {"rate": "8", "customer_enabled": False}


def test_the_page_needs_its_tick(client, db):
    mina = staff(db, "operator", "mina")   # a new sales user does not start with it
    assert client.get("/admin/installments/settings", headers=mina).status_code == 403
    assert client.post("/admin/installments/card", json=SHEET, headers=mina).status_code == 403


def test_changing_the_rate_needs_its_own_tick(client, db):
    mina = _sales(db, "installment.view,installment.edit")
    assert client.get("/admin/installments/settings", headers=mina).status_code == 200
    r = client.put("/admin/installments/settings", json={"rate": "9"}, headers=mina)
    assert r.status_code == 403
    boss = staff(db, "super_admin", "boss")
    r = client.put("/admin/installments/settings", json={"rate": "۹٫۵"}, headers=boss)
    assert r.status_code == 200 and r.json()["rate"] == "9.5"
    assert client.put("/admin/installments/settings", json={"rate": "abc"},
                      headers=boss).status_code == 422


def test_saving_needs_the_change_tick(client, db):
    mina = _sales(db, "installment.view")
    assert client.post("/admin/installments/card", json=SHEET, headers=mina).status_code == 200
    assert client.post("/admin/installments/quotes", json=SHEET, headers=mina).status_code == 403


def test_a_saved_quote_is_in_the_history(client, db):
    mina = _sales(db, "installment.view,installment.edit")
    row = client.post("/admin/installments/quotes", json=SHEET, headers=mina).json()
    assert row["interest"] == 40_000_000 and row["grand_total"] == 240_000_000
    assert row["status"] == "saved" and row["actor"] == "mina"
    rows = client.get("/admin/installments/quotes", headers=mina).json()
    assert [r["id"] for r in rows] == [row["id"]]


def test_each_sees_their_own_history_and_the_manager_all(client, db):
    boss = staff(db, "super_admin", "boss")
    client.post("/admin/installments/quotes", json=SHEET, headers=boss)
    mina = _sales(db, "installment.view,installment.edit")
    assert client.get("/admin/installments/quotes", headers=mina).json() == []
    client.post("/admin/installments/quotes", json=SHEET, headers=mina)
    assert len(client.get("/admin/installments/quotes", headers=boss).json()) == 2


def test_the_server_checks_a_sheet_again(client, db):
    boss = staff(db, "super_admin", "boss")
    for bad in ({"down": 300_000_000}, {"checks": [0, 5]}, {"rate": "x"}, {"dates": ["1405/13/01"]},
                {"checks": [1] * 25}, {"dates": ["1405/09/15"]}):
        r = client.post("/admin/installments/quotes", json={**SHEET, **bad}, headers=boss)
        assert r.status_code == 422, bad


def test_the_card_answer_has_no_interest(client, db):
    boss = staff(db, "super_admin", "boss")
    answer = client.post("/admin/installments/card", json=SHEET, headers=boss).json()
    assert answer["png_b64"] == "" and "۲۸٬۰۰۰٬۰۰۰" in answer["text"]
    assert "interest" not in answer["view"] and "rate" not in answer["view"]


def test_card_when_a_browser_works(client, db, monkeypatch):
    monkeypatch.setattr(installment_card, "render_png", lambda *a, **k: b"\x89PNGxx")
    boss = staff(db, "super_admin", "boss")
    answer = client.post("/admin/installments/card", json=SHEET, headers=boss).json()
    assert base64.b64decode(answer["png_b64"]) == b"\x89PNGxx"


def test_sending_makes_a_delivery_only_the_bot_can_read(client, db, reader):
    seed_products(reader)
    user_id = register_and_approve(client)
    boss = staff(db, "super_admin", "boss")
    row = client.post("/admin/installments/send", headers=boss,
                      json={"user_id": user_id, "sheet": SHEET}).json()
    assert row["status"] == "pending"
    assert "installment_card" in [e["kind"] for e in db.list_events(0, 100)]
    url = f"/admin/installments/deliveries/{row['id']}"
    assert client.get(url, headers=boss).status_code == 403
    delivery = client.get(url, headers=h("admin")).json()
    assert delivery["chat_id"] == "111" and delivery["platform"] == "bale"
    assert "سود" not in delivery["text"] and "rate" not in delivery and "interest" not in delivery
    r = client.post(f"{url}/result", json={"ok": False, "error": "x"}, headers=boss)
    assert r.status_code == 403
    client.post(f"{url}/result", json={"ok": True}, headers=h("admin"))
    assert client.get("/admin/installments/quotes",
                      headers=boss).json()[0]["status"] == "sent"


def test_a_rejected_customer_gets_nothing(client, db):
    user = client.post("/users/register", headers=h("bot"), json={
        "platform": "bale", "chat_id": "9", "name": "x", "phone": "09120000009"}).json()
    db.set_user_status(user["id"], "rejected")
    boss = staff(db, "super_admin", "boss")
    r = client.post("/admin/installments/send", headers=boss,
                    json={"user_id": user["id"], "sheet": SHEET})
    assert r.status_code == 404


def test_the_customer_list_gives_the_name_and_two_digits(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    mina = _sales(db, "installment.view,installment.edit")
    found = client.get("/admin/installments/customers", params={"q": "Ali"}, headers=mina).json()
    assert found == [{"id": 1, "name": "Ali", "platform": "bale", "phone_tail": "00"}]
    assert client.get("/admin/installments/customers", params={"q": "A"}, headers=mina).json() == []


def test_the_pick_list_gives_names_and_prices(client, db, reader):
    seed_products(reader)
    mina = _sales(db, "installment.view")
    rows = client.get("/admin/installments/items", headers=mina).json()
    assert rows and {"code", "name", "price"} == set(rows[0]) and rows[0]["price"] > 0


# ---- customers' own calculator (behind the switch) ---------------------------------------------
QUOTE = {"phone_name": "Galaxy", "price": 200_000_000, "down": 100_000_000, "months": 5}


def test_off_by_default_for_customers(client):
    assert client.get("/installments/settings", headers=h("bot")).json() == {"enabled": False}
    r = client.post("/installments/quote", json=QUOTE, headers=h("bot"))
    assert r.status_code == 403


def test_on_gives_the_card_and_never_the_rate(client, db):
    boss = staff(db, "super_admin", "boss")
    client.put("/admin/installments/settings", json={"customer_enabled": True}, headers=boss)
    r = client.post("/installments/quote", json=QUOTE, headers=h("bot"))
    assert r.status_code == 200
    answer = r.json()
    assert answer["view"]["grand_total"] == 240_000_000
    assert "rate" not in str(answer) and "interest" not in str(answer)
    assert len(answer["view"]["dates"]) == 5


def test_customers_use_the_saved_rate(client, db):
    boss = staff(db, "super_admin", "boss")
    client.put("/admin/installments/settings", json={"customer_enabled": True, "rate": "10"},
               headers=boss)
    answer = client.post("/installments/quote", json=QUOTE, headers=h("bot")).json()
    assert answer["view"]["grand_total"] == 250_000_000


@pytest.mark.parametrize("bad", [{"down": 300_000_000}, {"months": 0}, {"months": 30}])
def test_a_customers_bad_input_is_a_sentence(client, db, bad):
    boss = staff(db, "super_admin", "boss")
    client.put("/admin/installments/settings", json={"customer_enabled": True}, headers=boss)
    r = client.post("/installments/quote", json={**QUOTE, **bad}, headers=h("bot"))
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)


def test_the_card_goes_total_then_down_then_each_check():      # v2.18.2
    sheet = _sheet(price=190_000_000, dates=("1405/09/15", "1405/10/15", "1405/11/15",
                                             "1405/12/15", "1406/01/15"))
    page = installment_card.card_html(inst.customer_view(sheet))
    body = page[page.index("<body>"):]
    assert body.index("جمع کل") < body.index("پیش‌پرداخت") < body.index("<table>")
    assert body.count("<tr><td>") == 5 and inst.fa_text("1406/01/15") in body
    text = inst.customer_text(sheet)
    assert text.index("جمع کل") < text.index("پیش‌پرداخت") < text.index("چک ۵")
    for shown in (body, text):
        assert "سود" not in shown and "نرخ" not in shown
