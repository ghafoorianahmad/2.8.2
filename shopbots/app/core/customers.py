"""Customers: registration status and registration with shopapi.

Phase 2 (REQUIREMENTS §3) narrows registration to Bale's share-contact button;
this module is where that rule will live, independent of the channel.
"""
from __future__ import annotations

from ..shopapi import ShopApiClient
from ..utils import normalize_mobile

STATUS_NEW = "new"            # unknown to shopapi
STATUS_PENDING = "pending"
STATUS_REJECTED = "rejected"
STATUS_APPROVED = "approved"

DEFAULT_NAME = "مشتری"


class CustomerService:
    def __init__(self, api: ShopApiClient, *, max_name_len: int):
        self.api = api
        self.max_name_len = max_name_len

    async def status(self, platform: str, chat_id: str) -> str:
        user = await self.api.get_user(platform, chat_id)
        if user is None:
            return STATUS_NEW
        status = user.get("status")
        if status == "approved":
            return STATUS_APPROVED
        if status == "rejected":
            return STATUS_REJECTED
        return STATUS_PENDING

    def valid_name(self, text: str | None) -> str | None:
        name = (text or "").strip()
        if len(name) < 2 or len(name) > self.max_name_len or name.startswith("/"):
            return None
        return name

    @staticmethod
    def phone_from(text: str | None, contact: dict | None) -> str:
        """09xxxxxxxxx from a shared contact (preferred) or typed text; '' if invalid."""
        phone = ""
        if isinstance(contact, dict) and contact.get("phone_number"):
            phone = normalize_mobile(contact.get("phone_number"))
        return phone or normalize_mobile(text)

    async def register(self, platform: str, chat_id: str, name: str, phone: str) -> None:
        await self.api.register_user(platform, chat_id, (name or "").strip() or DEFAULT_NAME, phone)
