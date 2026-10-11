"""Customers: registration status and contact-only verification (REQUIREMENTS §3).

A customer registers ONLY by sharing their own contact with the platform's
share-contact button. A typed number is never accepted, and a shared contact
whose ``user_id`` is not the sender's own id is refused (somebody else's card).
shopapi then matches the number with the accounting software (recipe R4).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

from ..shopapi import ShopApiClient
from ..utils import normalize_mobile

STATUS_NEW = "new"            # unknown to shopapi
STATUS_PENDING = "pending"
STATUS_REJECTED = "rejected"
STATUS_APPROVED = "approved"

DEFAULT_NAME = "مشتری"


class ContactProblem(enum.Enum):
    NONE = "none"
    NO_CONTACT = "no_contact"    # text or anything else instead of the button
    NOT_OWN = "not_own"          # contact.user_id != from.id
    NOT_MOBILE = "not_mobile"


@dataclass
class VerifiedContact:
    phone: str = ""
    name: str = ""
    problem: ContactProblem = ContactProblem.NONE


def _join_name(first, last) -> str:
    return " ".join(str(p).strip() for p in (first, last) if p and str(p).strip())


class CustomerService:
    def __init__(self, api: ShopApiClient, *, max_name_len: int):
        self.api = api
        self.max_name_len = max_name_len

    async def status(self, platform: str, chat_id: str) -> str:
        return self.status_of(await self.api.get_user(platform, chat_id))

    @staticmethod
    def status_of(user: dict | None) -> str:
        if user is None:
            return STATUS_NEW
        status = user.get("status")
        if status == "approved":
            return STATUS_APPROVED
        if status == "rejected":
            return STATUS_REJECTED
        return STATUS_PENDING

    def clean_name(self, text: str | None) -> str:
        name = " ".join(str(text or "").split())[: self.max_name_len]
        return name if len(name) >= 2 and not name.startswith("/") else DEFAULT_NAME

    def verify_contact(
        self, contact: dict | None, sender_id, sender: dict | None = None
    ) -> VerifiedContact:
        """The sender's own verified number, or the reason it is refused."""
        if not isinstance(contact, dict) or not contact.get("phone_number"):
            return VerifiedContact(problem=ContactProblem.NO_CONTACT)
        owner = contact.get("user_id")
        if owner is None or sender_id is None or str(owner) != str(sender_id):
            return VerifiedContact(problem=ContactProblem.NOT_OWN)
        phone = normalize_mobile(contact.get("phone_number"))
        if not phone:
            return VerifiedContact(problem=ContactProblem.NOT_MOBILE)
        name = _join_name(contact.get("first_name"), contact.get("last_name"))
        if not name and isinstance(sender, dict):
            name = _join_name(sender.get("first_name"), sender.get("last_name"))
        return VerifiedContact(phone=phone, name=self.clean_name(name))

    async def register(self, platform: str, chat_id: str, contact: VerifiedContact) -> dict | None:
        return await self.api.register_user(platform, chat_id, contact.name, contact.phone)
