"""Persian labels for every shopapi status, plus status colours.

Keeping this in one module guarantees that the whole UI speaks the same
language and that no raw English status from the API is ever shown.
"""
from __future__ import annotations

from .persian import to_persian_digits

# --- customer (shopapi ``users``) statuses ---------------------------------
CUSTOMER_PENDING = "pending"
CUSTOMER_APPROVED = "approved"
CUSTOMER_REJECTED = "rejected"

CUSTOMER_STATUS_FA = {
    CUSTOMER_PENDING: "در انتظار تأیید",
    CUSTOMER_APPROVED: "تأیید شده",
    CUSTOMER_REJECTED: "رد شده",
}

# --- order statuses (shopapi schema CHECK constraint) ----------------------
ORDER_AWAITING_PAYMENT = "awaiting_payment"
ORDER_RECEIPT_UPLOADED = "receipt_uploaded"
ORDER_APPROVED = "approved"
ORDER_REJECTED = "rejected"
ORDER_WRITTEN = "written"
ORDER_CANCELLED = "cancelled"
ORDER_EXPIRED = "expired"

ORDER_STATUS_FA = {
    ORDER_AWAITING_PAYMENT: "در انتظار پرداخت",
    ORDER_RECEIPT_UPLOADED: "رسید رسیده",
    ORDER_APPROVED: "تأییدشده",
    ORDER_REJECTED: "ردشده",
    ORDER_WRITTEN: "ثبت‌شده در حسابداری",
    ORDER_CANCELLED: "لغو‌شده",
    ORDER_EXPIRED: "منقضی",
}

# --- platform labels -------------------------------------------------------
PLATFORM_FA = {
    "bale": "بله",
    "telegram": "تلگرام",
    "web": "وب‌سایت",
}

# --- role labels (internal admin users of this desktop app) ----------------
ROLE_SUPER_ADMIN = "super_admin"
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"

ROLE_FA = {
    ROLE_SUPER_ADMIN: "مدیر",
    ROLE_OPERATOR: "کاربر فروش",
    # earlier roles (the server maps them: admin -> مدیر, viewer -> کاربر فروش)
    ROLE_ADMIN: "مدیر",
    ROLE_VIEWER: "کاربر فروش",
}

# v2.7.0: the two roles a manager can give, most privileged first.
ALL_ROLES = (ROLE_SUPER_ADMIN, ROLE_OPERATOR)

ROLE_DESCRIPTION_FA = {
    ROLE_SUPER_ADMIN: "همهٔ بخش‌ها: سفارش‌ها، مشتریان، کالاها، لیست قیمت، فروش، تنظیمات و کاربران.",
    ROLE_OPERATOR: "سفارش‌ها (دیدن، تأیید رسید، ثبت ارسال، لغو)، درخواست‌های کالا و دیدن مشتریان.",
    ROLE_ADMIN: "همهٔ بخش‌ها.",
    ROLE_VIEWER: "سفارش‌ها، درخواست‌های کالا و دیدن مشتریان.",
}

# --- colours per status ----------------------------------------------------
_STATUS_COLORS = {
    CUSTOMER_PENDING: ("#B45309", "#FEF3C7"),
    CUSTOMER_APPROVED: ("#047857", "#D1FAE5"),
    CUSTOMER_REJECTED: ("#B91C1C", "#FEE2E2"),
    ORDER_AWAITING_PAYMENT: ("#B45309", "#FEF3C7"),
    ORDER_RECEIPT_UPLOADED: ("#1D4ED8", "#DBEAFE"),
    ORDER_APPROVED: ("#047857", "#D1FAE5"),
    ORDER_WRITTEN: ("#0F766E", "#CCFBF1"),
    ORDER_REJECTED: ("#B91C1C", "#FEE2E2"),
    ORDER_CANCELLED: ("#475569", "#E2E8F0"),
    ORDER_EXPIRED: ("#4B5563", "#F3F4F6"),
}
_DEFAULT_COLOR = ("#475569", "#E2E8F0")


def customer_status_fa(status: str | None) -> str:
    return CUSTOMER_STATUS_FA.get(str(status or ""), "نامشخص")


def order_status_fa(status: str | None) -> str:
    return ORDER_STATUS_FA.get(str(status or ""), "نامشخص")


def platform_fa(platform: str | None) -> str:
    return PLATFORM_FA.get(str(platform or ""), "نامشخص")


def role_fa(role: str | None) -> str:
    return ROLE_FA.get(str(role or ""), "نامشخص")


def status_colors(status: str | None) -> tuple[str, str]:
    """Foreground and background colour for a status pill."""
    return _STATUS_COLORS.get(str(status or ""), _DEFAULT_COLOR)


def person_code_fa(code: object) -> str:
    """Accounting person code, or a Persian placeholder when unset."""
    if code in (None, "", "None"):
        return "—"
    return to_persian_digits(code)
