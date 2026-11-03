"""Start ShopAdmin in the tray when the user signs in to Windows (per user).

A value under ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``; no
administrator rights, nothing for other users. The registry is reached through
a tiny adapter so tests never touch the real one.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Optional, Protocol

from .paths import app_dir, is_frozen

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ShopAdmin"
TRAY_FLAG = "--tray"


class Registry(Protocol):
    def get(self, name: str) -> Optional[str]: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class WindowsRunKey:
    def get(self, name: str) -> Optional[str]:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                return str(winreg.QueryValueEx(key, name)[0])
        except OSError:
            return None

    def set(self, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except OSError:
            pass


def tray_command() -> str:
    if is_frozen():
        return subprocess.list2cmdline([sys.executable, TRAY_FLAG])
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    return subprocess.list2cmdline([pythonw, str(app_dir() / "run_shopadmin.py"), TRAY_FLAG])


def apply_default(store, registry: Registry | None = None, *, frozen: bool | None = None) -> None:
    """v2.17.0: on by default for this Windows user, once: afterwards it stays what the
    user chose in «تنظیمات برنامه». Only the installed program registers itself."""
    if store.get_setting("autostart_initialized", False):
        return
    if not (is_frozen() if frozen is None else frozen):
        return
    set_enabled(True, registry)
    store.set_setting("autostart_initialized", True)


def is_enabled(registry: Registry | None = None) -> bool:
    value = (registry or WindowsRunKey()).get(VALUE_NAME)
    return bool(value and TRAY_FLAG in value)


def set_enabled(enabled: bool, registry: Registry | None = None) -> None:
    registry = registry or WindowsRunKey()
    if enabled:
        registry.set(VALUE_NAME, tray_command())
    else:
        registry.delete(VALUE_NAME)
