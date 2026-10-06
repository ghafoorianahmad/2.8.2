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
