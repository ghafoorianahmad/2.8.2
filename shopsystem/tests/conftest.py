import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _no_real_dotenv(monkeypatch):
    """Tests never read a real .env (a developer's ACCOUNTING_STATUS_CODE=0 or
    tokens would change results). Opt out only for live runs:
    SHOP_TESTS_USE_DOTENV=1."""
    if os.environ.get("SHOP_TESTS_USE_DOTENV") == "1":
        return
    import dotenv

    # launcher.load_env_file imports load_dotenv locally (real data dir .env).
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
