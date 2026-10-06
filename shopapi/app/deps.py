"""FastAPI dependency providers (overridden in tests)."""
from __future__ import annotations

from fastapi import Depends

from .accounting_reader import AccountingReader
from .accounting_writer import AccountingWriter
from .config import Settings, get_settings
from .db_own import OwnDB

_db_cache: dict[str, OwnDB] = {}


def get_db(settings: Settings = Depends(get_settings)) -> OwnDB:
    path = settings.sqlite_path
    if path not in _db_cache:
        _db_cache[path] = OwnDB(path)
    return _db_cache[path]


def get_reader(settings: Settings = Depends(get_settings)) -> AccountingReader:
    return AccountingReader(settings)


def get_writer(settings: Settings = Depends(get_settings)) -> AccountingWriter:
    return AccountingWriter(settings)
