from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import Settings  # noqa: E402
from app.gateway import TelegramGateway  # noqa: E402
from app.shopapi import WorkerApi  # noqa: E402
from app.worker import Worker  # noqa: E402
from fakes import FakeShopApi, FakeTelegram  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(api_id=12345, api_hash="h" * 32, worker_api_key="worker-key",
                    data_dir=tmp_path / "data", proxy_channels=["ProxyChan"],
                    local_proxies=[], connect_timeout_sec=5)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def env(settings):
    tg = FakeTelegram()
    shop = FakeShopApi()
    clock = Clock()
    api = WorkerApi(settings, transport=shop.transport())
    gateway = TelegramGateway(settings.api_id, settings.api_hash, timeout=5,
                              client_factory=tg.factory, clock=clock)
    worker = Worker(settings, api, gateway, load_session=lambda: "SESSION", clock=clock)
    return worker, tg, shop, clock
