"""Logging setup that cannot leak secrets.

httpx logs every request line at INFO level, and our Bot API URLs embed the bot
token (`https://.../bot<token>/sendMessage`). Those loggers are therefore always
capped at WARNING, so the token can never be written to a log file, a console or
a log collector — even when the application runs at DEBUG.

As a second line of defence every handler gets :class:`RedactingFilter`: an
exception text or a warning that still carries a token-bearing URL, an
``X-API-Key`` / ``Authorization`` header or a ``PWD=`` / ``password=`` value is
masked before it is written (REQUIREMENTS §10: secrets are never logged).
"""
from __future__ import annotations

import logging
import re

#: Third-party loggers that would otherwise print token-bearing URLs.
NOISY_LOGGERS = ("httpx", "httpcore")

DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

MASK = "***"
_PATTERNS = (
    # https://tapi.bale.ai/bot<token>/getUpdates, .../file/bot<token>/...
    (re.compile(r"(/bot)\d{3,15}:[A-Za-z0-9_-]{10,}"), r"\1" + MASK),
    # a bare Bot API token anywhere in a message
    (re.compile(r"\b\d{4,15}:[A-Za-z0-9_-]{30,}\b"), MASK),
    # headers / key=value pairs
    (re.compile(r"(?i)\b(x-api-key|authorization|bearer)(\s*[:=]?\s*)(bearer\s+)?[^\s,;'\"]{8,}"),
     r"\1\2\3" + MASK),
    (re.compile(r"(?i)(?<![a-z])(pwd|password|passphrase|api_key|secret|token)(\s*[=:]\s*)[^\s,;'\"]+"),
     r"\1\2" + MASK),
)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Masks secrets in the final message (args merged, exception text included)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken format must still be logged
            return True
        clean = redact(message)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if clean != message:
            record.msg, record.args = clean, None
        return True


def install_redaction(logger: logging.Logger | None = None) -> None:
    """Add the filter to every handler of ``logger`` (the root by default)."""
    target = logger or logging.getLogger()
    for handler in target.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())


def silence_noisy_loggers() -> None:
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    install_redaction()


def configure_logging(level: str | int = "INFO", fmt: str = DEFAULT_FORMAT) -> None:
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=level, format=fmt)
    silence_noisy_loggers()
