"""Errors shared by the UI worker and the (server-only) setup code.

Kept apart from ``server_setup`` so the staff-computer build can leave the
server setup modules out entirely.
"""
from __future__ import annotations


class SetupError(Exception):
    """A setup step failed; ``message`` is Persian and safe to show."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
