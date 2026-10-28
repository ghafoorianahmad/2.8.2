"""v2.14.0: other price channels: every new file / price post is sent once, with
the channel's name; pictures too; the first look takes only the newest few."""
from __future__ import annotations

import asyncio
import base64

from app import worker as worker_mod
from fakes import fake_message

PDF = b"%PDF-1.4 other list"


def run(coro):
    return asyncio.run(coro)


def test_other_price_channels_are_read_and_sent_once(env):
    worker, tg, shop, _ = env
    shop.roles = [{"ref": "karimi", "role": worker_mod.ROLE_PRICE_OTHER, "title": "کریمی"}]
    tg.channels["karimi"] = [fake_message(3, text="سلام"),
                             fake_message(4, text="A57 8/256 159000"),
                             fake_message(5, image=True),
                             fake_message(6, pdf=PDF)]
    run(worker.ensure_connected())
    assert run(worker.other_price_tick()) == 3
    kinds = [(f["title"], bool(f["data_b64"]), f["text"]) for f in shop.channel_files]
    assert kinds == [("کریمی", False, "A57 8/256 159000"), ("کریمی", True, ""),
                     ("کریمی", True, "")]
    assert base64.b64decode(shop.channel_files[2]["data_b64"]) == PDF
    assert run(worker.other_price_tick()) == 0            # nothing new
    tg.channels["karimi"].append(fake_message(9, text="Redmi 15C 66500"))
    assert run(worker.other_price_tick()) == 1


def test_no_other_channel_no_work(env):
    worker, tg, shop, _ = env
    run(worker.ensure_connected())
    assert run(worker.other_price_tick()) == 0 and shop.channel_files == []
