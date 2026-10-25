"""Pydantic request/response schemas."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, FiniteFloat

Platform = Literal["bale", "telegram", "web"]


class GroupOut(BaseModel):
    code: int
    name: str
    #: v2.6.1: the parent group in «سازه حساب» (Gkala.g_kala; 0 = a main group).
    parent: Optional[int] = None


class VariantOut(BaseModel):
    """One color of a phone priced from the distributor list (mapped rows only)."""
    id: int
    color: str
    #: v2.6.2: part / region code (ZAA, CHA …) or type (ویتنام …), picked after the color
    part: str = ""
    unit_price: Optional[float] = None   # Rial; None = no price (inquiry only)
    available: bool
    #: v2.9.2: the list changed this price by more than PRICE_GUARD_PCT (likely a
    #: misread): no price until a manager approves -> «درخواست خرید - استعلام قیمت»
    price_held: bool = False


class ProductOut(BaseModel):
    code: int
    name: str
    group: Optional[int] = None
    unit_price: float
    available_qty: float
    image: Optional[str] = None
    #: "accounting" (price level, stock), "pricelist" (per color, see variants) or
    #: "inquiry" (v2.6.1: no price is shown and it cannot be ordered).
    priced_by: str = "accounting"
    variants: Optional[list[VariantOut]] = None
    price_on_inquiry: bool = False
    #: v2.8.0 (phones): stock in «سازه حساب»; 0 = «درخواست خرید» only; None = not required
    stock_qty: Optional[float] = None


class ProductPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ProductOut]


class UserRegister(BaseModel):
    platform: Platform
    chat_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    phone: str = Field(min_length=1)


class UserOut(BaseModel):
    id: int
    platform: str
    chat_id: str
    name: str
    phone: str
    status: str
    person_code: Optional[int] = None
    created_at: str


class PersonMatch(BaseModel):
    code: int
    masked_name: Optional[str] = None


class OrderItemIn(BaseModel):
    kala_code: int = Field(gt=0)
    # Positive, finite and absolutely bounded so a client cannot reserve an
    # absurd amount (NaN/Infinity are rejected by FiniteFloat).
    qty: FiniteFloat = Field(gt=0, le=1_000_000)
    #: Required for products priced from the distributor list (the color).
    variant_id: Optional[int] = Field(default=None, gt=0)


class OrderCreate(BaseModel):
    platform: Platform
    chat_id: str = Field(min_length=1)
    items: list[OrderItemIn] = Field(min_length=1, max_length=100)


class OrderItemOut(BaseModel):
    kala_code: int
    name: str
    qty: float
    unit_price: float
    variant_id: Optional[int] = None
    variant: Optional[str] = None
    #: v2.6.2: the phone color and part the customer chose
    color: Optional[str] = None
    part: Optional[str] = None


class OrderOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    status: str
    price_level: int
    total: float
    #: Receipt deadline: the order is cancelled locally when no receipt arrived by then.
    reserve_until: Optional[str] = None
    accounting_order_no: Optional[int] = None
    #: The accounting database the order belongs to / was written to.
    accounting_db: Optional[str] = None
    #: Why a cancelled order was cancelled ('receipt_timeout').
    cancel_reason: Optional[str] = None
    #: v2.9.3: the short reason staff gave when they cancelled it (sent to the customer)
    cancel_note: Optional[str] = None
    created_at: str
    items: list[OrderItemOut]
    payment_instructions: Optional[str] = None
    #: Structured payment details for the pre-invoice card (None = not sent yet).
    payment_card_number: Optional[str] = None
    payment_sheba: Optional[str] = None
    payment_owner: Optional[str] = None
    #: v2.8.2: what staff typed for this order («ارسال اطلاعات پرداخت»): card_number,
    #: account_number, sheba, holder, bank, note (only the filled ones).
    payment_info: Optional[dict] = None
    payment_info_at: Optional[str] = None
    #: None | "partial" | "full" (recipe R5, synced from Facto.ordercode)
    invoice_state: Optional[str] = None
    invoiced_at: Optional[str] = None
    #: Accounting invoice numbers (facto.Numfact) of the order; filled for the bot (admin key) only.
    invoice_numbers: list[str] = []
    shipped_at: Optional[str] = None
    courier_name: Optional[str] = None
    courier_phone: Optional[str] = None
    has_receipt: bool = False
    #: The customer is not approved yet: the order is written to accounting
    #: only after approval.
    customer_pending: bool = False
    #: v2.6.0 (staff only): the customer's registration name, the linked
    #: accounting person code and the person's name in the accounting DB.
    user_name: Optional[str] = None
    user_person_code: Optional[int] = None
    person_name: Optional[str] = None
    #: v2.8.0 (staff): the customer's mobile (one-click copy), last change,
    #: ownership (names only for the manager), archive, the source purchase request
    user_phone: Optional[str] = None
    updated_at: Optional[str] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    owned: bool = False
    owned_by_me: bool = False
    finished: bool = False
    archived: bool = False
    archived_at: Optional[str] = None
    request_id: Optional[int] = None


class ReceiptIn(BaseModel):
    receipt_ref: str = Field(min_length=1, max_length=512)
    #: The image itself (JPEG/PNG, base64). Optional for old clients.
    data_b64: Optional[str] = Field(None, max_length=8_000_000)


class ApproveUserIn(BaseModel):
    #: Link to this existing person; omit to create a new person (recipe §5.1).
    person_code: Optional[int] = Field(None, gt=0)
    #: Name for the new person - staff correct the Bale profile name here.
    first_name: Optional[str] = Field(None, max_length=50)
    last_name: Optional[str] = Field(None, max_length=50)


class ShopStateIn(BaseModel):
    """Old switch: closed=true = «بستن فروش», false = «باز کردن فروش»."""
    closed: bool


class SalesActionIn(BaseModel):
    action: Literal["holiday", "close", "open"]


class ShopStateOut(BaseModel):
    """Sales state (v2.5.0). ``closed`` = orders are refused right now."""
    closed: bool
    updated_at: Optional[str] = None
    sales_open: bool = True
    #: list | manual_open | manual_close | holiday | weekday_closed | no_list |
    #: list_not_updated | windows_disabled
    reason: str = ""
    message_fa: str = ""
    #: When the current state ends by itself (ISO UTC), if known.
    until: Optional[str] = None
    list_id: Optional[int] = None
    list_date: str = ""
    list_slot: str = ""
    override: Optional[str] = None
    override_by: str = ""
    override_at: Optional[str] = None
    receipt_deadline_minutes: int = 30
    #: v2.6.0: a valid payment card is configured (else no checkout, ShopAdmin warns).
    payment_ready: bool = True
    #: v2.6.0: at least one product group is shown in the bot.
    catalog_ready: bool = True
    #: v2.6.1: at least one group is a phone group (else ShopAdmin warns).
    phone_groups_ready: bool = True


class StatementItem(BaseModel):
    date: str
    kind: str
    doc_no: str
    debit: float
    credit: float
    balance: float
    side: str
    description: str


class StatementOut(BaseModel):
    balance: float
    #: "debtor" (owes the shop) | "creditor" | "zero"
    side: str
    total: int
    page: int
    page_size: int
    items: list[StatementItem]


class RejectIn(BaseModel):
    reason: Optional[str] = None


# ---- staff accounts / sign-in ----
#: v2.7.0: «مدیر» = super_admin, «کاربر فروش» = operator. The old "admin" and
#: "viewer" are still accepted and stored as their new role.
StaffRole = Literal["super_admin", "admin", "operator", "viewer"]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    remember: bool = False
    client: str = Field("", max_length=100)


class StaffOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    active: bool
    must_change_password: bool
    locked: bool = False
    created_at: str
    last_login_at: Optional[str] = None
    #: v2.7.0: per-user ticks on top of the role, and the result
    extra_permissions: list[str] = []
    removed_permissions: list[str] = []
    permissions: list[str] = []


class LoginOut(BaseModel):
    token: str
    expires_at: str
    user: StaffOut
    permissions: list[str]


class MeOut(BaseModel):
    user: StaffOut
    permissions: list[str]


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class StaffCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    full_name: str = Field("", max_length=100)
    role: StaffRole = "operator"          # v2.7.0: new users are «کاربر فروش»
    password: str = Field(min_length=1, max_length=128)
    must_change_password: bool = True
    extra_permissions: list[str] = Field(default_factory=list, max_length=50)
    removed_permissions: list[str] = Field(default_factory=list, max_length=50)


class StaffUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=100)
    role: Optional[StaffRole] = None
    active: Optional[bool] = None
    extra_permissions: Optional[list[str]] = Field(None, max_length=50)
    removed_permissions: Optional[list[str]] = Field(None, max_length=50)


class PasswordResetIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    must_change_password: bool = True


class ForgotIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class ForgotOut(BaseModel):
    """Same shape whether or not the username exists (no enumeration)."""
    request_id: int
    token: str


class ForgotStatusIn(BaseModel):
    request_id: int
    token: str = Field(min_length=1, max_length=200)


class ForgotCompleteIn(ForgotStatusIn):
    new_password: str = Field(min_length=1, max_length=128)


class PasswordRequestOut(BaseModel):
    id: int
    staff_id: int
    username: str
    full_name: str = ""
    role: str
    created_at: str
    expires_at: str


class BootstrapIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    full_name: str = Field("", max_length=100)
    password: str = Field(min_length=1, max_length=128)


class InquiryIn(BaseModel):
    platform: Platform
    chat_id: str = Field(min_length=1)
    kala_code: int = Field(gt=0)
    variant_id: Optional[int] = Field(default=None, gt=0)


class InquiryOut(BaseModel):
    id: int
    user_id: int
    kala_code: int
    mapping_id: Optional[int] = None
    product_name: str = ""
    color: str = ""
    created_at: str
    customer_name: Optional[str] = None


class SecurityReportIn(BaseModel):
    """A suspicious act the bot saw (REQUIREMENTS §10); see security_watch.BOT_KINDS."""
    kind: str = Field(min_length=1, max_length=40)
    platform: Platform
    chat_id: str = Field(min_length=1, max_length=40)


# ---- v2.6.0: product groups, unavailable item requests, statement PDF data ----
class ProductGroupOut(BaseModel):
    code: int
    name: str
    show_in_bot: bool = False
    is_phone: bool = False
    price_on_inquiry: bool = False
    #: v2.6.1: parent group (None = a main group) and the flags in effect
    #: (own or inherited from an ancestor).
    parent: Optional[int] = None
    effective_show_in_bot: bool = False
    effective_is_phone: bool = False
    effective_price_on_inquiry: bool = False
    #: The group is configured here but no longer exists in the accounting DB.
    missing: bool = False


class ProductGroupSetting(BaseModel):
    code: int = Field(ge=0)
    show_in_bot: bool
    is_phone: bool
    price_on_inquiry: bool = False


class ProductGroupsIn(BaseModel):
    groups: list[ProductGroupSetting] = Field(max_length=5000)


class ItemRequestIn(BaseModel):
    platform: Platform
    chat_id: str = Field(min_length=1)
    #: A product picked from the search (optional) ...
    kala_code: Optional[int] = Field(default=None, gt=0)
    #: ... and/or what the customer typed.
    text: str = Field("", max_length=300)
    #: v2.6.1: "inquiry" = «استعلام قیمت» of a price-on-inquiry product.
    kind: Literal["unavailable", "inquiry"] = "unavailable"


class PurchaseRequestIn(BaseModel):
    """v2.8.0 «درخواست خرید»: a phone of the current list that cannot be ordered
    now (not mapped, or no stock in «سازه حساب»). The row by its key, or the
    product + the color variant (price_mappings.id) picked in the bot."""
    platform: Platform
    chat_id: str = Field(min_length=1)
    row_key: Optional[str] = Field(default=None, min_length=1, max_length=400)
    kala_code: Optional[int] = Field(default=None, gt=0)
    variant_id: Optional[int] = Field(default=None, gt=0)
    qty: int = Field(1, ge=1, le=20)


class AssignIn(BaseModel):
    staff_id: int = Field(gt=0)


class StockConfirmIn(BaseModel):
    """«تأیید موجودی»: map the row if it is not mapped yet, optionally a new price.
    v2.9.3: ``note`` = what staff wrote in «پیام به مشتری» (shown under the price)."""
    kala_code: Optional[int] = Field(default=None, gt=0)
    price_rial: Optional[int] = Field(default=None, gt=0, le=100_000_000_000)
    note: str = Field(default="", max_length=1000)


class OrderCancelIn(BaseModel):
    """v2.9.3: staff cancel an order, optionally with a short reason for the customer."""
    reason: str = Field(default="", max_length=200)


class ItemRequestOut(BaseModel):
    id: int
    user_id: int
    kala_code: Optional[int] = None
    product_name: str = ""
    text: str = ""
    status: str
    created_at: str
    handled_at: Optional[str] = None
    handled_by: str = ""
    customer_name: Optional[str] = None
    person_code: Optional[int] = None
    platform: Optional[str] = None
    #: v2.6.1
    kind: str = "unavailable"
    admin_note: str = ""
    note_at: Optional[str] = None
    note_by: str = ""
    customer_phone: Optional[str] = None
    messages_count: int = 0
    #: v2.8.0: ownership / archive (names only for the manager) and «درخواست خرید»
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    owned: bool = False
    owned_by_me: bool = False
    finished: bool = False
    archived: bool = False
    archived_at: Optional[str] = None
    accounting_db: Optional[str] = None
    row_key: Optional[str] = None
    mapping_id: Optional[int] = None
    color: str = ""
    part: str = ""
    price_rial: Optional[int] = None
    qty: float = 1
    outcome: str = ""
    order_id: Optional[int] = None
    #: v2.9.2: the price offered to the customer (waits for «تأیید و خرید»)
    offer_price_rial: Optional[int] = None
    offered_at: Optional[str] = None


class OfferAnswerIn(BaseModel):
    """v2.9.2: the customer's answer in the bot to an offered price (service key)."""
    accept: bool
    #: the offer the buttons belong to (a newer offer replaced it -> refused)
    price_rial: Optional[int] = Field(default=None, gt=0)


class ItemRequestStatusIn(BaseModel):
    status: Literal["new", "seen", "done"]


class ItemRequestNoteIn(BaseModel):
    note: str = Field("", max_length=1000)


class ItemRequestMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ItemRequestMessageOut(BaseModel):
    """A staff reply to an item request (v2.6.1); the bot delivers it."""
    id: int
    request_id: int
    text: str
    status: str
    error: str = ""
    created_at: str
    created_by: str = ""
    sent_at: Optional[str] = None
    purpose: str = ""
    #: v2.9.3: staff's own words inside the price message (purpose ``offer``)
    note: str = ""


class ItemRequestMessageDelivery(ItemRequestMessageOut):
    """What the bot needs to deliver one reply (service key only)."""
    platform: str
    chat_id: str
    product_name: str = ""
    request_text: str = ""
    kind: str = "unavailable"
    #: v2.9.2: ``offer`` = the price offer (the bot adds «تأیید و خرید» / «نمی‌خواهم»)
    color: str = ""
    part: str = ""
    qty: float = 1
    offer_price_rial: Optional[int] = None
    outcome: str = ""


class ItemRequestMessageResultIn(BaseModel):
    ok: bool
    error: str = Field("", max_length=300)


class RequestSearchItem(BaseModel):
    code: int
    name: str


class StatementRow(BaseModel):
    date: str
    kind: str
    doc_no: str
    description: str = ""
    debit: float
    credit: float
    balance: float
    side: str


class StatementFullOut(BaseModel):
    """Everything the statement PDF needs, oldest row first (v2.6.0)."""
    person_code: int
    customer_name: str = ""
    from_date: str = ""
    to_date: str = ""
    #: Balance carried over from rows older than the ones listed.
    opening_balance: float = 0.0
    opening_side: str = "zero"
    rows: list[StatementRow]
    #: Sums of the listed rows.
    total_debit: float = 0.0
    total_credit: float = 0.0
    balance: float
    side: str
    truncated: bool = False


class PaymentInfoIn(BaseModel):
    """v2.8.2: payment details typed by staff for one order; empty = left out."""
    card_number: str = Field("", max_length=40)
    account_number: str = Field("", max_length=40)
    sheba: str = Field("", max_length=40)
    holder: str = Field("", max_length=80)
    bank: str = Field("", max_length=60)
    note: str = Field("", max_length=300)


class ShipIn(BaseModel):
    """v2.7.0: «ارسال شد» with an optional courier (name and phone)."""
    courier_name: str = Field("", max_length=60)
    courier_phone: str = Field("", max_length=30)
