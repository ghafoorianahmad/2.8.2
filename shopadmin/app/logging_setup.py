"""Logging setup: UTF-8 ``app.log`` next to the executable, with masking.

Never log passwords, API keys, full phone numbers or full customer names.
``SecretFilter`` scrubs those patterns from every record before it is written.
"""
from __future__ import annotations

import logging
import logging.handlers
import re
from typing import Any

from .paths import APP_NAME, log_path

_LOGGER_NAME = "shopadmin"
_configured = False

# --- masking rules ---------------------------------------------------------
# Long digit runs are treated as phone numbers / codes and masked.
_PHONE_RE = re.compile(r"(?<!\d)(\d{4})\d{4,}(?!\d)")
# Anything that looks like an API key / token assignment.
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|password|passwd|secret|authorization|bearer)\b"
    r"(\s*[:=]\s*|\s+)([^\s,;\"']+)"
)
# Long opaque strings (>=24 chars of key-ish alphabet) are masked outright.
_TOKENLIKE_RE = re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")


def mask_phone(phone: str | None) -> str:
    """Mask a phone number for display/logging: ``09121234567`` -> ``09*****67``."""
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return "****"
    if len(digits) <= 4:
        return "*" * len(digits)
    return f"{digits[:2]}{'*' * (len(digits) - 4)}{digits[-2:]}"


def mask_name(name: str | None) -> str:
    """Mask a customer name: keep only the first character."""
    text = str(name or "").strip()
    if not text:
        return ""
    if len(text) <= 1:
        return text
    return text[0] + "*" * (len(text) - 1)


def mask_secret(value: Any) -> str:
    """Show only the length of a secret."""
    text = str(value or "")
    return f"<{len(text)} chars>"


def scrub(text: str) -> str:
    """Apply every masking rule to a free-text log message."""
    out = _SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{mask_secret(m.group(3))}", text)
    out = _PHONE_RE.sub(lambda m: mask_phone(m.group(0)), out)
    out = _TOKENLIKE_RE.sub(lambda m: mask_secret(m.group(0)), out)
    return out


class SecretFilter(logging.Filter):
    """Scrub secrets out of the record before any handler sees it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        cleaned = scrub(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        if record.exc_text:
            record.exc_text = scrub(record.exc_text)
        return True


def get_logger(name: str | None = None) -> logging.Logger:
    base = logging.getLogger(_LOGGER_NAME)
    return base.getChild(name) if name else base


def setup_logging(level: int = logging.INFO, to_file: bool = True) -> logging.Logger:
    """Configure the root application logger exactly once."""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    secret_filter = SecretFilter()

    if to_file:
        try:
            path = log_path()
            handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            handler.setFormatter(formatter)
            handler.addFilter(secret_filter)
            logger.addHandler(handler)
        except OSError:
            pass  # no writable location: console logging only

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(secret_filter)
    logger.addHandler(console)

    _configured = True
    logger.info("--- %s started ---", APP_NAME)
    return logger


def reset_logging() -> None:
    """Test helper: forget the configuration so it can be applied again."""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    _configured = False
