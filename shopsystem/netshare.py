"""v2.13.0: sign in to another computer's share for the off-server backup copy.

The service runs as the virtual account «NT SERVICE\\ShopServer». Towards another
computer it has no user name at all (in a workgroup it arrives as an anonymous
caller), so a share such as ``\\\\192.168.20.150\\E`` - which the owner opens with
his own saved user name - answers "Access is denied" (the nightly backup from
1405/08/04 on). With ``BACKUP_SHARE_USER`` / ``BACKUP_SHARE_PASSWORD`` (an account
of THAT computer) the service opens its own connection to the share for the
copy, and closes it again afterwards. Nothing is mapped to a drive letter; the
password never reaches a log or a command line.

Also imported by the API (same ShopSystem process) for «آزمایش» with the
service account; outside Windows / without credentials it does nothing.
"""
from __future__ import annotations

import contextlib
import re
import sys
from typing import Iterator, Optional

_UNC = re.compile(r"^[\\/]{2}([^\\/]+)[\\/]+([^\\/]+)")
#: WNet errors worth a Persian sentence (the rest are reported by number)
ERROR_FA = {
    5: "دسترسی نیست: این حساب در رایانهٔ مقصد اجازهٔ نوشتن در این پوشهٔ اشتراکی را ندارد.",
    53: "رایانهٔ مقصد در شبکه پیدا نشد (روشن و وصل است؟).",
    67: "پوشهٔ اشتراکی با این نام روی رایانهٔ مقصد نیست.",
    86: "گذرواژهٔ حساب رایانهٔ مقصد نادرست است.",
    1219: "این رایانه با نام کاربری دیگری به همین رایانهٔ مقصد وصل است؛ یک نام کاربری برای "
          "هر دو به کار ببرید.",
    1326: "نام کاربری یا گذرواژهٔ رایانهٔ مقصد نادرست است.",
    1327: "این حساب در رایانهٔ مقصد محدود است (گذرواژهٔ خالی یا ساعت ورود).",
    1331: "این حساب در رایانهٔ مقصد غیرفعال است.",
}


class ShareLoginError(OSError):
    """The share refused the sign-in; ``message_fa`` says why in Persian."""

    def __init__(self, code: int, message_fa: str) -> None:
        super().__init__(code, message_fa)
        self.code = code
        self.message_fa = message_fa


def share_root(folder: str) -> Optional[str]:
    """``\\\\host\\share\\sub`` -> ``\\\\host\\share``; None for a local path."""
    match = _UNC.match(str(folder or "").strip())
    if not match:
        return None
    return f"\\\\{match.group(1)}\\{match.group(2)}"


def _connect(remote: str, user: str, password: str) -> None:  # pragma: no cover - Windows
    import ctypes
    from ctypes import wintypes

    class NETRESOURCE(ctypes.Structure):
        _fields_ = [("dwScope", wintypes.DWORD), ("dwType", wintypes.DWORD),
                    ("dwDisplayType", wintypes.DWORD), ("dwUsage", wintypes.DWORD),
                    ("lpLocalName", wintypes.LPWSTR), ("lpRemoteName", wintypes.LPWSTR),
                    ("lpComment", wintypes.LPWSTR), ("lpProvider", wintypes.LPWSTR)]

    resource = NETRESOURCE()
    resource.dwType = 1                     # RESOURCETYPE_DISK
    resource.lpRemoteName = remote
    mpr = ctypes.WinDLL("mpr", use_last_error=True)
    code = mpr.WNetAddConnection2W(ctypes.byref(resource), password, user, 0)
    if code == 1219:
        # a connection to this share exists already (this process): use it
        return
    if code != 0:
        raise ShareLoginError(code, ERROR_FA.get(code, f"ورود به پوشهٔ اشتراکی ممکن نشد (کد {code})."))


def _disconnect(remote: str) -> None:  # pragma: no cover - Windows
    import ctypes

    try:
        ctypes.WinDLL("mpr").WNetCancelConnection2W(remote, 0, True)
    except OSError:
        pass


@contextlib.contextmanager
def session(folder: str, user: str, password: str, *, connect=None,
            disconnect=None) -> Iterator[bool]:
    """Signed in to the share of ``folder`` for the ``with`` block. Yields True when
    a sign-in was made (a network folder and a user name), False otherwise."""
    remote = share_root(folder)
    user = str(user or "").strip()
    if remote is None or not user:
        yield False
        return
    if connect is None:
        if sys.platform != "win32":
            yield False
            return
        connect, disconnect = _connect, _disconnect
    connect(remote, user, password or "")
    try:
        yield True
    finally:
        if disconnect is not None:
            disconnect(remote)
