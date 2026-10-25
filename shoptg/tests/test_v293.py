"""v2.9.3: the pool aims at 10 fast proxies: with 7 working, new links are tested
(2.9.2 aimed at 5 and tested none of 55); a slow proxy (> 5 s) does not count."""
from __future__ import annotations

import asyncio

from fakes import fake_message, pool_entry

LINKS = [f"tg://proxy?server=n{i}.example&port=443&secret=dd{'ab' * 16}" for i in range(6)]


def run(coro):
    return asyncio.run(coro)


def working(pid: int, latency: int = 400) -> dict:
    return {**pool_entry(pid, f"10.0.0.{pid}"), "last_ok_at": "2026-10-25T08:00:00+00:00",
            "failing_now": False, "last_latency_ms": latency}


def test_default_target_is_ten(settings):
    assert settings.pool_size == 10


def test_seven_working_still_tests_new_links(env):
    worker, tg, shop, _ = env
    shop.pool = [working(i) for i in range(1, 8)]
    tg.channels["ProxyChan"] = [fake_message(5, text="\n".join(LINKS))]
    run(worker.ensure_connected())
    added = run(worker.collect_tick(force=True))
    assert added == 5                   # 12 wanted (10 + spare 2), 7 there: 5 more
    assert worker.collect_info["tested"] == 5


def test_slow_proxies_do_not_count_as_healthy(env):
    worker, _tg, shop, _ = env
    shop.pool = [working(1), working(2, latency=7000), {**working(3), "failing_now": True}]
    assert run(worker.healthy_count()) == 1
