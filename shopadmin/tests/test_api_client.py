"""Tests for the shopapi HTTP client — fully mocked, no real network."""
from __future__ import annotations

import httpx
import pytest

from app.api_client import (
    MSG_CONNECTION_FAILED,
    MSG_FORBIDDEN,
    MSG_INVALID_KEY,
    MSG_NOT_FOUND,
    MSG_SERVER_ERROR,
    MSG_TIMEOUT,
    ApiAuthError,
    ApiConnectionError,
    ApiError,
    ShopApiClient,
    SystemInfo,
    translate_detail,
)


# ---- connection plumbing --------------------------------------------------
def test_health_needs_no_key(fake_api):
    client = ShopApiClient("http://x.test", "", transport=httpx.MockTransport(fake_api.handler))
    try:
        assert client.health()["status"] == "ok"
    finally:
        client.close()


def test_api_key_is_sent_in_the_x_api_key_header(api, fake_api):
    api.list_customers()
    assert ("GET", "/admin/users") in fake_api.requests


def test_missing_base_url_raises_persian_error():
    client = ShopApiClient("", "key")
    try:
        with pytest.raises(ApiError) as exc:
            client.list_customers()
        assert "آدرس سرور" in exc.value.message
    finally:
        client.close()


def test_trailing_slash_in_base_url_is_tolerated(fake_api):
    client = ShopApiClient(
        "http://x.test/", "admin-key", transport=httpx.MockTransport(fake_api.handler)
    )
    try:
        assert client.list_customers() == []
    finally:
        client.close()


# ---- error handling -------------------------------------------------------
def test_connection_error_is_reported_in_persian(fake_api):
    fake_api.offline = True
    client = ShopApiClient("http://x.test", "admin-key", transport=httpx.MockTransport(fake_api.handler))
    try:
        with pytest.raises(ApiConnectionError) as exc:
            client.list_customers()
        assert exc.value.message == MSG_CONNECTION_FAILED
        assert exc.value.kind == "connection"
    finally:
        client.close()


def test_timeout_is_reported_in_persian(fake_api):
    def slow(request):
        raise httpx.ReadTimeout("too slow", request=request)

    client = ShopApiClient("http://x.test", "admin-key", transport=httpx.MockTransport(slow))
    try:
        with pytest.raises(ApiError) as exc:
            client.list_customers()
        assert exc.value.message == MSG_TIMEOUT
        assert exc.value.kind == "timeout"
    finally:
        client.close()


def test_invalid_api_key_raises_auth_error(fake_api):
    client = ShopApiClient("http://x.test", "wrong-key", transport=httpx.MockTransport(fake_api.handler))
    try:
        with pytest.raises(ApiAuthError) as exc:
            client.list_customers()
        assert exc.value.status_code == 401
        assert exc.value.message == MSG_INVALID_KEY
    finally:
        client.close()


def test_missing_api_key_raises_auth_error(fake_api):
    client = ShopApiClient("http://x.test", "", transport=httpx.MockTransport(fake_api.handler))
    try:
        with pytest.raises(ApiAuthError):
            client.list_customers()
    finally:
        client.close()


def test_403_uses_the_admin_key_message(fake_api):
    fake_api.force_status = 403
    fake_api.force_detail = "Admin key required"
    client = ShopApiClient("http://x.test", "admin-key", transport=httpx.MockTransport(fake_api.handler))
    try:
        with pytest.raises(ApiAuthError) as exc:
            client.list_customers()
        assert exc.value.message == MSG_FORBIDDEN
    finally:
        client.close()


def test_503_is_explained_as_accounting_unavailable(fake_api):
    fake_api.force_status = 503
    fake_api.force_detail = "Accounting database unavailable"
    client = ShopApiClient("http://x.test", "admin-key", transport=httpx.MockTransport(fake_api.handler))
    try:
        with pytest.raises(ApiError) as exc:
            client.list_products()
        assert "حسابداری" in exc.value.message
    finally:
        client.close()


def test_insufficient_stock_message_is_persian(fake_api):
    fake_api.force_status = 409
    fake_api.force_detail = "Insufficient stock for product 101"
    client = ShopApiClient("http://x.test", "admin-key", transport=httpx.MockTransport(fake_api.handler))
    try:
        with pytest.raises(ApiError) as exc:
            client.approve_payment(1)
        message = exc.value.message
        assert "موجودی کافی نیست" in message
        assert "۱۰۱" in message
        assert "Insufficient" not in message
    finally:
        client.close()


def test_non_json_error_body_does_not_crash(fake_api):
    def html_error(request):
        return httpx.Response(500, text="<html>boom</html>", request=request)

    client = ShopApiClient("http://x.test", "admin-key", transport=httpx.MockTransport(html_error))
    try:
        with pytest.raises(ApiError) as exc:
            client.list_orders()
        assert exc.value.message  # always something Persian-ish, never empty
        assert "خطای سرور فروشگاه" in exc.value.message
    finally:
        client.close()


def test_raw_html_never_reaches_the_user_untranslated():
    message = translate_detail("<html>boom</html>", 500)
    assert message.startswith("خطای سرور")


def test_invalid_json_on_success_is_a_decode_error(fake_api):
    def bad_json(request):
        return httpx.Response(200, text="not json", request=request)

    client = ShopApiClient("http://x.test", "admin-key", transport=httpx.MockTransport(bad_json))
    try:
        with pytest.raises(ApiError) as exc:
            client.list_customers()
        assert exc.value.kind == "decode"
    finally:
        client.close()


# ---- detail translation table --------------------------------------------
@pytest.mark.parametrize(
    "detail,expected_fragment",
    [
        ("Insufficient stock for product 55", "موجودی کافی نیست"),
        ("person_code 123 not found", "کد شخص"),
        ("person_code 123 is already linked to another user", "قبلاً به مشتری دیگری"),
        ("Order in status written; cannot approve", "وضعیت"),
        ("Order in status approved; cannot reject", "قابل رد کردن نیست"),
        ("User not found", "مشتری یافت نشد"),
        ("Order not found", "سفارش یافت نشد"),
        ("No matching person", "پیدا نشد"),
        ("Accounting database unavailable", "حسابداری"),
        ("Invalid API key", MSG_INVALID_KEY),
        ("Admin key required", MSG_FORBIDDEN),
    ],
)
def test_known_shopapi_errors_are_translated(detail, expected_fragment):
    assert expected_fragment in translate_detail(detail, 409)


def test_unknown_english_detail_is_not_shown_raw():
    message = translate_detail("SomeBrandNewEnglishError", 500)
    assert "SomeBrandNewEnglishError" in message  # prefixed, but never bare
    assert message.startswith("خطای سرور")


def test_persian_detail_from_server_is_kept():
    assert translate_detail("موجودی انبار کافی نیست", 409) == "موجودی انبار کافی نیست"


def test_validation_error_list_becomes_persian():
    detail = [
        {"loc": ["body", "person_code"], "msg": "Input should be greater than 0", "type": "greater_than"}
    ]
    message = translate_detail(detail, 422)
    assert "نامعتبر" in message
    assert "person_code" in message


def test_empty_detail_falls_back_by_status():
    assert translate_detail("", 404) == MSG_NOT_FOUND
    assert translate_detail(None, 500) == MSG_SERVER_ERROR


# ---- endpoints ------------------------------------------------------------
def test_list_customers_filters_by_status(fake_api, api):
    fake_api.add_customer(name="الف", status="pending")
    fake_api.add_customer(name="ب", status="approved", person_code=7001)
    fake_api.add_customer(name="ج", status="rejected")
    assert len(api.list_customers()) == 3
    assert len(api.list_customers("pending")) == 1
    assert len(api.list_customers("approved")) == 1
    assert api.list_customers("pending")[0]["name"] == "الف"


def test_approve_customer_sends_the_person_code(fake_api, api):
    customer = fake_api.add_customer()
    result = api.approve_customer(customer["id"], 7001)
    assert result["status"] == "approved"
    assert result["person_code"] == 7001


def test_reject_customer(fake_api, api):
    customer = fake_api.add_customer()
    assert api.reject_customer(customer["id"], "اطلاعات ناقص")["status"] == "rejected"


def test_person_match_returns_none_on_404(fake_api, api):
    assert api.match_person("09120000000") is None
    fake_api.persons["09120000000"] = {"code": 7001, "masked_name": "ع***"}
    assert api.match_person("09120000000")["code"] == 7001


def test_person_match_reraises_other_errors(fake_api, api):
    fake_api.force_status = 500
    fake_api.force_detail = "boom"
    with pytest.raises(ApiError):
        api.match_person("09120000000")


def test_orders_always_send_an_explicit_status(fake_api, api):
    fake_api.add_order(status="receipt_uploaded")
    fake_api.add_order(status="written")
    assert len(api.list_orders("receipt_uploaded")) == 1
    assert len(api.list_orders("written")) == 1
    assert len(api.list_orders()) == 1  # shopapi's own default


def test_approve_payment(fake_api, api):
    order = fake_api.add_order()
    result = api.approve_payment(order["id"])
    assert result["status"] == "written"
    assert result["accounting_order_no"] == 5001


def test_reject_payment(fake_api, api):
    order = fake_api.add_order()
    assert api.reject_payment(order["id"])["status"] == "rejected"


def test_approving_a_non_pending_order_is_rejected_with_persian_text(fake_api, api):
    order = fake_api.add_order(status="written")
    with pytest.raises(ApiError) as exc:
        api.approve_payment(order["id"])
    assert "نوشته‌شده در حسابداری" in exc.value.message


def test_list_products_passes_filters(fake_api, api):
    fake_api.products = {
        1: {"code": 1, "name": "کالای الف", "group": 10, "unit_price": 1000.0,
            "available_qty": 5.0, "image": None},
        2: {"code": 2, "name": "کالای ب", "group": 20, "unit_price": 2000.0,
            "available_qty": 0.0, "image": None},
    }
    page = api.list_products()
    assert page["total"] == 2
    assert api.list_products(query="الف")["total"] == 1
    assert api.list_products(group=20)["total"] == 1


def test_list_products_rejects_a_non_object_payload():
    def bad(request):
        return httpx.Response(200, json=[1, 2, 3], request=request)

    client = ShopApiClient("http://x.test", "k", transport=httpx.MockTransport(bad))
    try:
        with pytest.raises(ApiError):
            client.list_products()
    finally:
        client.close()


def test_list_groups(fake_api, api):
    fake_api.groups = [{"code": 1, "name": "گروه یک"}]
    assert api.list_groups()[0]["name"] == "گروه یک"


def test_expire_orders(fake_api, api):
    assert isinstance(api.expire_orders(), dict)


# ---- system info ----------------------------------------------------------
def test_system_info_reports_the_dry_run_flag(fake_api, api):
    fake_api.write_enabled = False
    info = api.system_info()
    assert info.accounting_write_enabled is False
    assert info.reachable is True
    fake_api.write_enabled = True
    assert api.system_info().accounting_write_enabled is True


def test_system_info_keeps_unknown_fields_in_extra():
    info = SystemInfo.from_payload({"accounting_write_enabled": True, "future_flag": 7})
    assert info.extra["future_flag"] == 7


def test_system_info_unavailable_helper():
    info = SystemInfo.unavailable()
    assert info.reachable is False
    assert info.accounting_write_enabled is False


def test_system_info_missing_endpoint_degrades_gracefully(fake_api):
    """An older shopapi build (404) must not break the connection check."""
    fake_api.force_status = 404
    fake_api.force_detail = "Not Found"
    client = ShopApiClient("http://x.test", "admin-key",
                           transport=httpx.MockTransport(fake_api.handler))
    try:
        info = client.system_info()
        assert info.supported is False
        assert info.reachable is False
        assert info.write_mode_known is False
        # The health check still works, so the app stays usable.
        assert client.health()["status"] == "ok"
    finally:
        client.close()


def test_test_connection_survives_a_missing_system_info_endpoint(fake_api):
    """health + system-info: the second one 404s, and that must not be fatal."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/admin/system-info":
            return httpx.Response(404, json={"detail": "Not Found"}, request=request)
        return fake_api.handler(request)

    client = ShopApiClient("http://x.test", "admin-key",
                           transport=httpx.MockTransport(handler))
    try:
        info = client.test_connection()  # must not raise
        assert info.supported is False
        assert info.reachable is False
    finally:
        client.close()


def test_write_mode_known_flag():
    assert SystemInfo(reachable=True, supported=True).write_mode_known is True
    assert SystemInfo(reachable=True, supported=False).write_mode_known is False
    assert SystemInfo(reachable=False, supported=True).write_mode_known is False


def test_test_connection_returns_system_info(fake_api, api):
    assert api.test_connection().price_level_bot == 1


def test_test_connection_raises_when_offline(fake_api, api):
    fake_api.offline = True
    with pytest.raises(ApiConnectionError):
        api.test_connection()


def test_configure_swaps_the_connection_target(fake_api):
    client = ShopApiClient("http://old.test", "old-key", transport=httpx.MockTransport(fake_api.handler))
    try:
        client.configure("http://new.test/", "admin-key")
        assert client.base_url == "http://new.test"
        assert client.api_key == "admin-key"
        assert client.list_customers() == []
    finally:
        client.close()


def test_no_secret_leaks_into_logs(fake_api, caplog):
    import logging

    client = ShopApiClient("http://x.test", "admin-key", transport=httpx.MockTransport(fake_api.handler))
    try:
        with caplog.at_level(logging.DEBUG, logger="shopadmin"):
            client.list_customers()
        assert "admin-key" not in caplog.text
    finally:
        client.close()
