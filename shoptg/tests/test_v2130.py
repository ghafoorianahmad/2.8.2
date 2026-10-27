"""v2.13.0: «دریافت لیست اکنون», the status while Telegram makes the reader wait,
the watchdog (heartbeat + a round of jobs that hangs) and the channel looked up
once across reconnects."""
from __future__ import annotations

import asyncio
import json

import pytest

from app import worker as worker_mod
from app.gateway import TelegramGateway
from app.main import heartbeat_writer
from fakes import fake_message

PDF = b"%PDF-1.4 list"


def run(coro):
    return asyncio.run(coro)


def test_fetch_now_sends_the_newest_list_again_even_unchanged(env):
    worker, tg, shop, _ = env
    tg.channels["AbrishamiiPhoneMashhad"] = [fake_message(7, pdf=PDF)]
    run(worker.ensure_connected())
    assert run(worker.price_tick()) == 1
    assert run(worker.price_tick()) == 0               # same version: not sent again
    shop.state["tg_price_request"] = "2026-10-27T18:00:00+00:00"
    assert run(worker.request_tick()) is True
    assert len(shop.pricelists) == 2                   # forced
    assert shop.state["tg_price_done"] == "2026-10-27T18:00:00+00:00"
    assert run(worker.request_tick()) is False         # handled once


def test_fetch_now_waits_for_a_connection(env):
    worker, tg, shop, _ = env
    tg.channels["AbrishamiiPhoneMashhad"] = [fake_message(7, pdf=PDF)]
    shop.state["tg_price_request"] = "2026-10-27T18:00:00+00:00"
    assert run(worker.request_tick()) is False         # not connected: stays asked
    assert "tg_price_done" not in shop.state
    run(worker.ensure_connected())
    assert run(worker.request_tick()) is True
    assert len(shop.pricelists) == 1


class FloodWaitError(Exception):
    def __init__(self, seconds):
        super().__init__("flood")
        self.seconds = seconds


def test_status_is_published_while_paused_and_a_long_wait_alerts(env):
    worker, tg, shop, clock = env
    run(worker.ensure_connected())
    assert worker._flood(FloodWaitError(7200), clock()) is True
    run(worker.step())
    status = json.loads(shop.state["tg_status"])
    assert status["paused_until"] and "7200" in status["error"]
    shop.state.pop("tg_status")
    clock.t += 30
    run(worker.step())                                 # within a minute: not again
    assert "tg_status" not in shop.state
    clock.t += 31
    run(worker.step())
    assert "tg_status" in shop.state

    async def one_round():
        stop = asyncio.Event()

        async def stopper():
            await asyncio.sleep(0.05)
            stop.set()
        asyncio.get_running_loop().create_task(stopper())
        await worker.run(stop)
    run(one_round())
    assert worker_mod.ALERT_FLOOD in shop.alerts


def test_a_round_that_hangs_stops_the_reader(env):
    worker, *_ = env

    async def hang():
        await asyncio.sleep(10)
    worker.step = hang
    with pytest.raises(worker_mod.WorkerStuck):
        run(worker.run(asyncio.Event(), step_timeout=0.05))


def test_heartbeat_file_is_touched(env, tmp_path):
    worker, *_ = env
    beat_file = tmp_path / "shoptg.heartbeat"
    worker.s.heartbeat_file = str(beat_file)
    beats = []
    beat = heartbeat_writer(worker.s)

    def counted():
        beats.append(1)
        beat()

    async def main():
        stop = asyncio.Event()
        task = asyncio.get_running_loop().create_task(worker.run(stop, heartbeat=counted))
        await asyncio.sleep(0.05)
        stop.set()
        await task
    run(main())
    assert beats and beat_file.read_text().isdigit()
    worker.s.heartbeat_file = ""
    assert heartbeat_writer(worker.s) is None


def test_channel_is_looked_up_once_across_reconnects(settings):
    from fakes import FakeClient, FakeTelegram

    tg = FakeTelegram()
    lookups = []

    class Client(FakeClient):
        async def get_input_entity(self, target):
            lookups.append(target)
            return target                         # the fake channels are keyed by name

    def factory(session, api_id, api_hash, **kwargs):
        client = Client(tg, session, api_id, api_hash, kwargs)
        tg.clients.append(client)
        return client

    tg.channels["Chan"] = [fake_message(1, text="x")]
    gateway = TelegramGateway(1, "h" * 32, timeout=5, client_factory=factory)

    async def main():
        for _ in range(3):
            await gateway.connect("S", None)
            assert [m.id for m in await gateway.messages("Chan")] == [1]
            await gateway.disconnect()
    run(main())
    assert lookups == ["Chan"]
