"""Which edition of ShopAdmin this is.

* **server edition** (ShopServerSetup): runs on the shop server, which staff
  reach only through Remote Desktop. It shows NO login screen — it signs in as
  the server console (see ``AuthService.console_sign_in``).
* **client edition** (ShopAdminSetup, staff computers): username + password.

The client build is made without ``app.server_setup`` (``build_shopadmin.py
--variant client``), so the presence of that module IS the edition. For
development, ``SHOPADMIN_EDITION=client|server`` overrides it.
"""
from __future__ import annotations

import os

EDITION_SERVER = "server"
EDITION_CLIENT = "client"


def edition() -> str:
    forced = os.getenv("SHOPADMIN_EDITION", "").strip().lower()
    if forced in (EDITION_SERVER, EDITION_CLIENT):
        return forced
    try:
        from . import server_setup  # noqa: F401  (absent from the client build)
    except ImportError:
        return EDITION_CLIENT
    return EDITION_SERVER


def is_server_edition() -> bool:
    return edition() == EDITION_SERVER
