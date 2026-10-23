"""Long-lived login tokens for «مرا به خاطر بسپار».

v2.9.1 (owner's decision): the last user's password is ALSO kept on this computer,
encrypted with Windows DPAPI for the signed-in Windows user only
(``remembered.pw``), so after «خروج» pressing «ورود» is enough. Where DPAPI does
not exist (tests on Linux) nothing is stored; there is never a plain-text or
merely obfuscated copy. Otherwise a random refresh token is stored:

* the token itself → the Windows Credential Manager (via ``keyring``),
* a SHA-256 hash of it → the local SQLite database,

so a stolen database file alone cannot be used to log in.

If the OS keyring is unavailable, the token is written to an obfuscated file
inside the application data folder and a clear warning is written to app.log.
The fallback is never plain text.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Optional

from .logging_setup import get_logger
from .paths import APP_NAME, data_dir

log = get_logger("credentials")

SERVICE_NAME = f"{APP_NAME}-Desktop"
ACCOUNT_NAME = "remembered-login"
FALLBACK_FILENAME = "remembered.token"

MSG_KEYRING_WARNING = (
    "کلیدخانهٔ ویندوز در دسترس نیست؛ نشانهٔ ورود خودکار در یک پروندهٔ پوشیده در "
    "پوشهٔ داده‌های برنامه ذخیره می‌شود (هرگز به‌صورت متن روشن)."
)

try:  # optional dependency: falls back to the local file when absent
    import keyring  # type: ignore

    _HAS_KEYRING = True
except Exception:  # pragma: no cover - depends on the environment
    keyring = None  # type: ignore
    _HAS_KEYRING = False


# --------------------------------------------------------------------------
# backend selection
# --------------------------------------------------------------------------
def keyring_available() -> bool:
    """True only when a real, working keyring backend is present.

    ``keyring`` ships several backends; the null/fail ones accept writes and
    silently discard them, which would look like a successful save and then lose
    the login. Those are treated as unavailable.
    """
    if not _HAS_KEYRING:
        return False
    try:
        backend = keyring.get_keyring()  # type: ignore[union-attr]
    except Exception as exc:  # pragma: no cover - backend specific
        log.warning("keyring backend lookup failed: %s", type(exc).__name__)
        return False
    name = type(backend).__name__.lower()
    if "fail" in name or "null" in name:
        return False
    try:
        # A real round-trip is the only reliable proof.
        keyring.get_password(SERVICE_NAME, "__probe__")  # type: ignore[union-attr]
    except Exception as exc:
        log.warning("keyring is present but unusable: %s", type(exc).__name__)
        return False
    return True


def backend_name() -> str:
    if not _HAS_KEYRING:
        return "none"
    try:
        return type(keyring.get_keyring()).__name__  # type: ignore[union-attr]
    except Exception:  # pragma: no cover
        return "unknown"


# --------------------------------------------------------------------------
# fallback file (obfuscated, never plain text)
# --------------------------------------------------------------------------
def _fallback_path() -> Path:
    return data_dir() / FALLBACK_FILENAME


def _obfuscate(value: str) -> str:
    """XOR-with-SHA256 + base64. Obfuscation, not encryption — see docstring."""
    digest = hashlib.sha256(APP_NAME.encode("utf-8")).digest()
    raw = value.encode("utf-8")
    mixed = bytes(byte ^ digest[index % len(digest)] for index, byte in enumerate(raw))
    return base64.urlsafe_b64encode(mixed).decode("ascii")


def _deobfuscate(value: str) -> Optional[str]:
    try:
        mixed = base64.urlsafe_b64decode(value.encode("ascii"))
    except Exception:
        return None
    digest = hashlib.sha256(APP_NAME.encode("utf-8")).digest()
    raw = bytes(byte ^ digest[index % len(digest)] for index, byte in enumerate(mixed))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


DPAPI_PREFIX = "dpapi:"


def _dpapi(data: bytes, protect: bool) -> Optional[bytes]:
    """Windows DPAPI: encryption bound to the signed-in Windows user.

    Another Windows account (or a copy of the file on another computer) cannot
    decrypt it. Returns ``None`` where DPAPI does not exist.
    """
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:  # pragma: no cover
        return None
    if not hasattr(ctypes, "windll"):
        return None

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = func(ctypes.byref(blob_in), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN,
              ctypes.byref(blob_out))
    if not ok:
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def encode_fallback(secret: str) -> str:
    """DPAPI-encrypted where available; obfuscated only as a last resort."""
    protected = _dpapi(secret.encode("utf-8"), protect=True)
    if protected is not None:
        return DPAPI_PREFIX + base64.urlsafe_b64encode(protected).decode("ascii")
    return _obfuscate(secret)


def decode_fallback(value: str) -> Optional[str]:
    if value.startswith(DPAPI_PREFIX):
        try:
            raw = base64.urlsafe_b64decode(value[len(DPAPI_PREFIX):].encode("ascii"))
        except Exception:
            return None
        plain = _dpapi(raw, protect=False)
        try:
            return plain.decode("utf-8") if plain is not None else None
        except UnicodeDecodeError:
            return None
    return _deobfuscate(value)


def _write_fallback(username: str, token: str) -> bool:
    try:
        path = _fallback_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # "<username>\n<obfuscated token>" so the file is self-describing.
        path.write_text(
            f"{username}\n{encode_fallback(token)}\n", encoding="utf-8"
        )
        try:  # best effort: keep it to the current user on Windows
            import os
            import stat

            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass
        return True
    except OSError as exc:
        log.error("could not write the remember-me fallback file: %s", type(exc).__name__)
        return False


def _read_fallback(username: str) -> Optional[str]:
    path = _fallback_path()
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.warning("could not read the remember-me fallback file: %s", type(exc).__name__)
        return None
    if len(lines) < 2:
        return None
    stored_username, encoded = lines[0].strip(), lines[1].strip()
    if stored_username.lower() != str(username).strip().lower():
        return None
    return decode_fallback(encoded)


def _clear_fallback() -> None:
    try:
        _fallback_path().unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover
        log.warning("could not delete the remember-me fallback file: %s", type(exc).__name__)


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def _account(username: str) -> str:
    return f"{ACCOUNT_NAME}:{username}"


def save_token(username: str, token: str) -> str:
    """Store the token. Returns the backend actually used: 'keyring' or 'file'."""
    if keyring_available():
        try:
            keyring.set_password(SERVICE_NAME, _account(username), token)  # type: ignore[union-attr]
            _clear_fallback()  # never keep a stale second copy
            log.info("remember-me token stored in the OS keyring (%s)", backend_name())
            return "keyring"
        except Exception as exc:  # pragma: no cover - backend specific
            log.warning("keyring save failed (%s); using the local file",
                        type(exc).__name__)

    log.warning(MSG_KEYRING_WARNING)
    if _write_fallback(username, token):
        return "file"
    return "none"


def load_token(username: str) -> Optional[str]:
    if keyring_available():
        try:
            value = keyring.get_password(SERVICE_NAME, _account(username))  # type: ignore[union-attr]
            if value:
                return value
        except Exception as exc:  # pragma: no cover
            log.warning("keyring read failed: %s", type(exc).__name__)
    return _read_fallback(username)


def clear_token(username: str) -> None:
    """Remove the token from BOTH stores (used on logout / unchecking)."""
    if keyring_available():
        try:
            keyring.delete_password(SERVICE_NAME, _account(username))  # type: ignore[union-attr]
        except Exception:
            pass  # already absent is fine
    _clear_fallback()


# --------------------------------------------------------------------------
# v2.9.1: the remembered password (DPAPI only)
# --------------------------------------------------------------------------
PASSWORD_FILENAME = "remembered.pw"


def _password_path() -> Path:
    return data_dir() / PASSWORD_FILENAME


def dpapi_available() -> bool:
    return _dpapi(b"probe", protect=True) is not None


def save_password(username: str, password: str) -> bool:
    """Keep the last user's password, DPAPI-encrypted; False when not possible."""
    if not username or not password:
        return False
    protected = _dpapi(password.encode("utf-8"), protect=True)
    if protected is None:
        log.info("remembered password not stored: Windows DPAPI is not available")
        return False
    try:
        path = _password_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{username}\n{DPAPI_PREFIX}"
                        f"{base64.urlsafe_b64encode(protected).decode('ascii')}\n",
                        encoding="utf-8")
        return True
    except OSError as exc:
        log.warning("remembered password not stored: %s", type(exc).__name__)
        return False


def load_password(username: str) -> Optional[str]:
    """The remembered password of ``username`` on this computer (or None)."""
    path = _password_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if len(lines) < 2 or lines[0].strip().lower() != str(username or "").strip().lower():
        return None
    value = lines[1].strip()
    if not value.startswith(DPAPI_PREFIX):
        return None
    return decode_fallback(value)


def clear_password() -> None:
    try:
        _password_path().unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover
        log.warning("could not delete the remembered password: %s", type(exc).__name__)


# Backwards-compatible aliases (older call sites / tests used these names).
save_remembered = save_token
load_remembered = load_token
clear_remembered = clear_token
