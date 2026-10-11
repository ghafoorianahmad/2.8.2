"""Payment receipt images: validation and storage in the receipts folder.

Only JPEG and PNG are accepted, recognised by their first bytes (the declared
type is not trusted), up to ``RECEIPT_MAX_BYTES``. Files are named by order id
and time only, so a stored name never contains customer data.
"""
from __future__ import annotations

import base64
import binascii
import secrets
from pathlib import Path

from .util import now_utc

SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)


class ReceiptError(ValueError):
    pass


def sniff(data: bytes) -> tuple[str, str] | None:
    for magic, content_type, ext in SIGNATURES:
        if data.startswith(magic):
            return content_type, ext
    return None


def decode(data_b64: str, max_bytes: int) -> tuple[bytes, str, str]:
    """Decode and validate. Returns (bytes, content_type, extension)."""
    # base64 is 4/3 of the size: refuse oversized input before decoding it.
    if len(data_b64) > (max_bytes * 4) // 3 + 8:
        raise ReceiptError("too large")
    try:
        data = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise ReceiptError("not base64") from None
    if not data:
        raise ReceiptError("empty")
    if len(data) > max_bytes:
        raise ReceiptError("too large")
    kind = sniff(data)
    if kind is None:
        raise ReceiptError("only JPEG or PNG images are accepted")
    return data, kind[0], kind[1]


def store(folder: Path, order_id: int, data: bytes, ext: str) -> str:
    """Write the image and return its file name (relative to ``folder``)."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = now_utc().strftime("%Y%m%dT%H%M%S")
    name = f"order{int(order_id)}_{stamp}_{secrets.token_hex(4)}.{ext}"
    tmp = folder / (name + ".part")
    tmp.write_bytes(data)
    tmp.replace(folder / name)
    return name


def resolve(folder: Path, file_name: str) -> Path | None:
    """The stored file, only if the name stays inside ``folder``."""
    path = (folder / file_name).resolve()
    try:
        path.relative_to(folder.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None
