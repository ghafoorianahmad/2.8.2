"""ShopAdmin — Persian desktop admin console for the shopapi REST API.

The GUI imports live in :mod:`app.ui`; this module stays import-light so that the
core (config, storage, auth, API client) can be tested without Qt.
"""

from .paths import APP_NAME, APP_TITLE_FA, APP_VERSION

__all__ = ["APP_NAME", "APP_TITLE_FA", "APP_VERSION"]
