"""Encrypted Telegram session file (REQUIREMENTS §5, §10).

The Telethon session string is the full account (whoever has it *is* the shop's
Telegram account), so on disk it is:

* encrypted with DPAPI, **LocalMachine** scope: any account on this server can
  decrypt it, which is what lets the Phase 4 service account use a session
  created by the administrator. Copied to another PC it is useless;
* protected by an NTFS ACL (inheritance removed): SYSTEM and Administrators
  full control, plus read for ``TG_SERVICE_ACCOUNT`` when set. Because DPAPI
  LocalMachine alone would let every local user decrypt, the ACL is the real
  barrier between the session and other users of the server.

A per-application entropy string is added to the DPAPI call; it is not a
secret, it only stops a generic "decrypt every LocalMachine blob" tool from
recognizing the file as ours.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

MAGIC = b"SHOPTG-DPAPI-1\n"
ENTROPY = b"shoptg/telegram-session/v1"

CRYPTPROTECT_UI_FORBIDDEN = 0x01
CRYPTPROTECT_LOCAL_MACHINE = 0x04

# Well-known SIDs: names differ by Windows language, SIDs do not.
SID_SYSTEM = "*S-1-5-18"
SID_ADMINISTRATORS = "*S-1-5-32-544"


class SecureStoreError(Exception):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _crypt(data: bytes, *, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise SecureStoreError("DPAPI is only available on Windows")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    data_in, _keep1 = _blob(data)
    entropy, _keep2 = _blob(ENTROPY)
    out = _Blob()
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
            CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(out))
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        code = ctypes.GetLastError()
        what = "encrypt" if protect else "decrypt"
        raise SecureStoreError(f"DPAPI could not {what} the session (Windows error {code})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def protect(data: bytes) -> bytes:
    return _crypt(data, protect=True)


def unprotect(blob: bytes) -> bytes:
    return _crypt(blob, protect=False)


def acl_args(path: Path, service_account: str = "") -> list[str]:
    """icacls arguments: drop inherited entries, SYSTEM+Administrators full."""
    grants = [f"{SID_SYSTEM}:(F)", f"{SID_ADMINISTRATORS}:(F)"]
    if service_account:
        grants.append(f"{service_account}:(R)")
    return ["icacls", str(path), "/inheritance:r", "/grant:r", *grants]


def restrict_acl(path: Path, service_account: str = "", *, runner=subprocess.run) -> None:
    result = runner(acl_args(path, service_account), capture_output=True, text=True)
    if result.returncode != 0:
        raise SecureStoreError(
            f"icacls failed on {path.name} (exit {result.returncode}); "
            "run this from an elevated (Administrator) PowerShell")


def ensure_private_dir(path: Path, service_account: str = "", *, runner=subprocess.run) -> None:
    """Create the data folder and give it the same restricted ACL."""
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        grants = [f"{SID_SYSTEM}:(OI)(CI)(F)", f"{SID_ADMINISTRATORS}:(OI)(CI)(F)"]
        if service_account:
            grants.append(f"{service_account}:(OI)(CI)(RX)")
        args = ["icacls", str(path), "/inheritance:r", "/grant:r", *grants]
        result = runner(args, capture_output=True, text=True)
        if result.returncode != 0:
            raise SecureStoreError(
                f"icacls failed on {path} (exit {result.returncode}); "
                "run this from an elevated (Administrator) PowerShell")


def save_session(path: Path, session: str, service_account: str = "", *,
                 protector=protect, runner=subprocess.run) -> None:
    if not session:
        raise SecureStoreError("empty session")
    ensure_private_dir(path.parent, service_account, runner=runner)
    blob = MAGIC + protector(session.encode("ascii"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    # The folder ACL already applies to the new file; write, then swap.
    with open(tmp, "wb") as fh:
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    if sys.platform == "win32":
        restrict_acl(path, service_account, runner=runner)


def load_session(path: Path, *, unprotector=unprotect) -> str:
    """The decrypted session string; SecureStoreError if absent/unreadable."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise SecureStoreError("no Telegram session yet: run login.ps1") from None
    except PermissionError:
        raise SecureStoreError(
            "access to the session file was denied: run as Administrator / the service account"
        ) from None
    if not raw.startswith(MAGIC):
        raise SecureStoreError("the session file is not in the expected format")
    return unprotector(raw[len(MAGIC):]).decode("ascii")


def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False
