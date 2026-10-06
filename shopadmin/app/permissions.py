"""Role-based permissions.

A single table drives every access decision in the UI so that a Viewer can never
see an action button and an Operator can never approve a payment.
"""
from __future__ import annotations

from dataclasses import dataclass

from .statuses import ROLE_ADMIN, ROLE_OPERATOR, ROLE_SUPER_ADMIN, ROLE_VIEWER

# --- permission names ------------------------------------------------------
DASHBOARD_VIEW = "dashboard.view"
CUSTOMERS_VIEW = "customers.view"
CUSTOMERS_APPROVE = "customers.approve"
CUSTOMERS_REJECT = "customers.reject"
ORDERS_VIEW = "orders.view"
ORDERS_APPROVE_PAYMENT = "orders.approve_payment"
ORDERS_REJECT_PAYMENT = "orders.reject_payment"
ORDERS_UPLOAD_RECEIPT = "orders.upload_receipt"
PRODUCTS_VIEW = "products.view"
REPORTS_VIEW = "reports.view"
REPORTS_EXPORT = "reports.export"
SETTINGS_VIEW = "settings.view"
SETTINGS_EDIT_CONNECTION = "settings.edit_connection"
SETTINGS_EDIT_GENERAL = "settings.edit_general"
SETTINGS_CHANGE_OWN_PASSWORD = "settings.change_own_password"
SETTINGS_VIEW_LOG = "settings.view_log"
USERS_VIEW = "users.view"
USERS_MANAGE = "users.manage"
SERVER_MANAGE = "server.manage"

ALL_ROLES = (ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER)

# Viewer: read-only. Operator: process orders + upload receipts, no approvals.
# Admin: approvals. Super admin: everything, including internal users.
PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_VIEWER: frozenset(
        {
            DASHBOARD_VIEW,
            CUSTOMERS_VIEW,
            ORDERS_VIEW,
            PRODUCTS_VIEW,
            REPORTS_VIEW,
            SETTINGS_VIEW,
            SETTINGS_CHANGE_OWN_PASSWORD,
            SETTINGS_VIEW_LOG,
        }
    ),
    ROLE_OPERATOR: frozenset(
        {
            DASHBOARD_VIEW,
            CUSTOMERS_VIEW,
            ORDERS_VIEW,
            ORDERS_UPLOAD_RECEIPT,
            PRODUCTS_VIEW,
            REPORTS_VIEW,
            REPORTS_EXPORT,
            SETTINGS_VIEW,
            SETTINGS_CHANGE_OWN_PASSWORD,
            SETTINGS_VIEW_LOG,
        }
    ),
    ROLE_ADMIN: frozenset(
        {
            DASHBOARD_VIEW,
            CUSTOMERS_VIEW,
            CUSTOMERS_APPROVE,
            CUSTOMERS_REJECT,
            ORDERS_VIEW,
            ORDERS_APPROVE_PAYMENT,
            ORDERS_REJECT_PAYMENT,
            ORDERS_UPLOAD_RECEIPT,
            PRODUCTS_VIEW,
            REPORTS_VIEW,
            REPORTS_EXPORT,
            SETTINGS_VIEW,
            SETTINGS_EDIT_GENERAL,
            SETTINGS_CHANGE_OWN_PASSWORD,
            SETTINGS_VIEW_LOG,
        }
    ),
    ROLE_SUPER_ADMIN: frozenset(
        {
            DASHBOARD_VIEW,
            CUSTOMERS_VIEW,
            CUSTOMERS_APPROVE,
            CUSTOMERS_REJECT,
            ORDERS_VIEW,
            ORDERS_APPROVE_PAYMENT,
            ORDERS_REJECT_PAYMENT,
            ORDERS_UPLOAD_RECEIPT,
            PRODUCTS_VIEW,
            REPORTS_VIEW,
            REPORTS_EXPORT,
            SETTINGS_VIEW,
            SETTINGS_EDIT_CONNECTION,
            SETTINGS_EDIT_GENERAL,
            SETTINGS_CHANGE_OWN_PASSWORD,
            SETTINGS_VIEW_LOG,
            USERS_VIEW,
            USERS_MANAGE,
            SERVER_MANAGE,
        }
    ),
}


def role_permissions(role: str | None) -> frozenset[str]:
    return PERMISSIONS.get(str(role or ""), frozenset())


def has_permission(role: str | None, permission: str) -> bool:
    return permission in role_permissions(role)


@dataclass(frozen=True)
class Principal:
    """The signed-in internal admin user."""

    user_id: int
    username: str
    full_name: str
    role: str

    @property
    def can(self) -> "PermissionCheck":
        return PermissionCheck(self.role)

    @property
    def is_super_admin(self) -> bool:
        return self.role == ROLE_SUPER_ADMIN


class PermissionCheck:
    """``principal.can(ORDERS_APPROVE_PAYMENT)`` reads nicely at call sites."""

    __slots__ = ("_role",)

    def __init__(self, role: str) -> None:
        self._role = role

    def __call__(self, permission: str) -> bool:
        return has_permission(self._role, permission)
