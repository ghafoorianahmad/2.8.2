"""Pydantic request/response schemas."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, FiniteFloat

Platform = Literal["bale", "telegram", "web"]


class GroupOut(BaseModel):
    code: int
    name: str


class ProductOut(BaseModel):
    code: int
    name: str
    group: Optional[int] = None
    unit_price: float
    available_qty: float
    image: Optional[str] = None


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


class OrderCreate(BaseModel):
    platform: Platform
    chat_id: str = Field(min_length=1)
    items: list[OrderItemIn] = Field(min_length=1, max_length=100)


class OrderItemOut(BaseModel):
    kala_code: int
    name: str
    qty: float
    unit_price: float


class OrderOut(BaseModel):
    id: int
    status: str
    price_level: int
    total: float
    reserve_until: Optional[str] = None
    accounting_order_no: Optional[int] = None
    created_at: str
    items: list[OrderItemOut]
    payment_instructions: Optional[str] = None


class ReceiptIn(BaseModel):
    receipt_ref: str = Field(min_length=1)


class ApproveUserIn(BaseModel):
    person_code: int = Field(gt=0)


class RejectIn(BaseModel):
    reason: Optional[str] = None


# ---- staff accounts / sign-in ----
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
    role: StaffRole
    password: str = Field(min_length=1, max_length=128)
    must_change_password: bool = True


class StaffUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=100)
    role: Optional[StaffRole] = None
    active: Optional[bool] = None


class PasswordResetIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    must_change_password: bool = True


class BootstrapIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    full_name: str = Field("", max_length=100)
    password: str = Field(min_length=1, max_length=128)
