"""Channel-independent shop logic shared by every bot channel.

Nothing here knows about a Bot API, keyboards or message texts: the services take
and return plain data, and `engine.py` renders it for a PlatformAdapter. Adding a
channel = one adapter in `app/platforms/` (REQUIREMENTS §1).

- catalog:   groups, product pages, search-text normalization (ی/ي, ک/ك, digits)
- cart:      per-chat cart with quantity limits
- orders:    checkout, receipt upload, a customer's orders
- customers: registration status, contact-only verification, registration
"""
from __future__ import annotations

from .cart import MAX_QTY, CartService
from .catalog import CatalogService, Product, ProductPage, normalize_search, parse_product_ref
from .customers import (
    STATUS_APPROVED,
    STATUS_NEW,
    STATUS_PENDING,
    STATUS_REJECTED,
    ContactProblem,
    CustomerService,
    VerifiedContact,
)
from .orders import (
    CheckoutResult,
    OrderService,
    ReceiptOutcome,
    receipt_file,
    receipt_file_ref,
)

__all__ = [
    "MAX_QTY",
    "CartService",
    "CatalogService",
    "Product",
    "ProductPage",
    "normalize_search",
    "parse_product_ref",
    "STATUS_APPROVED",
    "STATUS_NEW",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "ContactProblem",
    "CustomerService",
    "VerifiedContact",
    "CheckoutResult",
    "OrderService",
    "ReceiptOutcome",
    "receipt_file",
    "receipt_file_ref",
]
