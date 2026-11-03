"""Application metadata and filesystem paths.

Everything the app persists lives in ONE per-user folder so that the installed
``.exe`` works on a machine where the installation directory is read-only
(``C:\\Program Files``) while still keeping the log next to the executable when
that location is writable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ShopAdmin"
APP_TITLE_FA = "مدیریت فروشگاه"
APP_VERSION = "2.18.0"  # keep equal to installer/ShopAdmin.iss MyAppVersion (test_version.py)

ORG_NAME = "ShopAdmin"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Directory the program was started from (the folder holding the .exe)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def resource_dir() -> Path:
    """Directory holding bundled read-only resources (fonts, icons, assets)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    # source layout: <repo>/shopadmin/app/paths.py -> <repo>/shopadmin
    return Path(__file__).resolve().parent.parent


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    """Writable folder for the local SQLite database and logs."""
    override = os.getenv("SHOPADMIN_DATA_DIR", "").strip()
    if override:
        target = Path(override)
        target.mkdir(parents=True, exist_ok=True)
        return target

    local = os.getenv("LOCALAPPDATA", "").strip()
    if local:
        target = Path(local) / APP_NAME
    else:  # pragma: no cover - non-Windows fallback
        target = Path.home() / f".{APP_NAME.lower()}"

    if _writable(target):
        return target
    # Last resort: next to the executable.
    fallback = app_dir() / "data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def db_path() -> Path:
    return data_dir() / "shopadmin.db"


def log_path() -> Path:
    return data_dir() / "app.log"


def assets_dir() -> Path:
    """``app/assets`` (source tree and the PyInstaller bundle); ``assets`` as a
    fallback. v2.7.0: the fonts were looked up in ``assets`` only and never found,
    so the app silently fell back to Tahoma instead of Vazirmatn."""
    for candidate in (resource_dir() / "app" / "assets", resource_dir() / "assets"):
        if candidate.exists():
            return candidate
    return resource_dir() / "app" / "assets"


def fonts_dir() -> Path:
    return assets_dir() / "fonts"


def icons_dir() -> Path:
    return assets_dir() / "icons"
