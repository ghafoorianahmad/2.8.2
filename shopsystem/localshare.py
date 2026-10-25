"""v2.9.2: a network share that is on THIS computer -> its local folder.

The service runs as the virtual account «NT SERVICE\\ShopServer». Through
``\\\\<this PC>\\Share`` it reaches its own disk as a network client, where the
share's permissions (not the folder's) apply and usually refuse it; the local
folder behind the share can be granted to the account directly. So a backup
destination ``\\\\THIS-PC\\Backups\\Shop`` is used (and suggested) as
``D:\\Backups\\Shop``.

Same file in ``shopadmin/app/localshare.py`` (the setup wizard suggests the
local path; the service converts it again at run time).
"""
from __future__ import annotations

import os
import re
import socket
from pathlib import PureWindowsPath
from typing import Callable, Iterable, Mapping, Optional

_UNC = re.compile(r"^[\\/]{2}([^\\/]+)[\\/]+([^\\/]+)[\\/]*(.*)$")
_SHARES_KEY = r"SYSTEM\CurrentControlSet\Services\LanmanServer\Shares"


def this_computer_names() -> set[str]:
    """Names and addresses that mean this computer (lower case)."""
    names = {"localhost", "127.0.0.1", "::1", "."}
    for value in (os.environ.get("COMPUTERNAME"), socket.gethostname()):
        if value:
            names.add(value.lower())
    try:
        fqdn = socket.getfqdn()
        if fqdn:
            names.add(fqdn.lower())
            names.add(fqdn.split(".")[0].lower())
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            names.add(str(info[4][0]).lower())
    except OSError:
        pass
    return names


def share_folders() -> dict[str, str]:
    """Shares of this computer ({name (lower case): local folder}) from the
    registry (readable without administrator rights). Empty when not Windows."""
    try:
        import winreg
    except ImportError:
        return {}
    out: dict[str, str] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _SHARES_KEY) as key:
            index = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                lines = value if isinstance(value, (list, tuple)) else str(value).split("\0")
                for line in lines:
                    if str(line).lower().startswith("path="):
                        out[str(name).lower()] = str(line)[5:]
    except OSError:
        return out
    return out


def local_path_for(folder: str, *, names: Optional[Iterable[str]] = None,
                   shares: Optional[Mapping[str, str]] = None,
                   shares_loader: Optional[Callable[[], Mapping[str, str]]] = None
                   ) -> Optional[str]:
    """``\\\\THIS-PC\\Share\\sub`` -> ``<share folder>\\sub``; None when ``folder`` is
    not a share of this computer (another computer, a local path, unknown share)."""
    match = _UNC.match(str(folder or "").strip())
    if not match:
        return None
    host, share, rest = match.group(1).lower(), match.group(2), match.group(3)
    if host not in {n.lower() for n in (names if names is not None else this_computer_names())}:
        return None
    if re.fullmatch(r"[A-Za-z]\$", share):           # administrative share D$ -> D:\
        base = f"{share[0].upper()}:\\"
    else:
        if shares is None:
            shares = (shares_loader or share_folders)()
        found = shares.get(share.lower())
        if not found:
            return None
        base = found
    path = PureWindowsPath(base)
    for part in re.split(r"[\\/]+", rest):
        if part:
            path = path / part
    return str(path)
