"""Logging setup that cannot leak secrets.

httpx logs every request line at INFO level, and our Bot API URLs embed the bot
token (`https://.../bot<token>/sendMessage`). Those loggers are therefore always
capped at WARNING, so the token can never be written to a log file, a console or
a log collector — even when the application runs at DEBUG.
"""
from __future__ import annotations

import logging

#: Third-party loggers that would otherwise print token-bearing URLs.
NOISY_LOGGERS = ("httpx", "httpcore")

DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def silence_noisy_loggers() -> None:
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(level: str | int = "INFO", fmt: str = DEFAULT_FORMAT) -> None:
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=level, format=fmt)
    silence_noisy_loggers()
