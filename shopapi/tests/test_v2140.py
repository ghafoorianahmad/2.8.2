"""v2.14.0: archive names, per-item price approval, price channels, self-check."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from app.pricelist import importer, pdf_archive
from app.pricelist.repo import PriceListRepo

from .test_phase3 import _fake_list
from .test_v2130 import WHEN


def test_odd_archive_names_get_the_standard_name(db, settings, tmp_path, monkeypatch):
    settings.pricelists_dir = str(tmp_path)
    monkeypatch.setattr(pdf_archive, "now_utc", lambda: WHEN)
    monkeypatch.setattr(importer, "parse_pdf", lambda data: _fake_list("1405/08/05"))
    importer.import_pdf(db, settings, b"%PDF-A", source="manual")
    repo = PriceListRepo(db)
    list_id = repo.list_lists()[0]["id"]
    # an older build kept the file under another name
    (tmp_path / "1405-08-05-1.pdf").rename(tmp_path / "pricelist_16_unknown.pdf")
    repo.set_file_name(list_id, "pricelist_16_unknown.pdf")
    stamp = WHEN.timestamp()
    os.utime(tmp_path / "pricelist_16_unknown.pdf", (stamp, stamp))
    (tmp_path / "notes.txt").write_text("x")
    assert pdf_archive.normalize_archive(db, settings) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["1405-08-05-1.pdf", "notes.txt"]
    assert repo.list_lists()[0]["file_name"] == "1405-08-05-1.pdf"
    assert pdf_archive.normalize_archive(db, settings) == 0
    assert datetime.fromtimestamp(stamp, timezone.utc) == WHEN


# ---- other price channels --------------------------------------------------------------
from datetime import timedelta  # noqa: E402

from app import purchase  # noqa: E402
from app.pricelist import channels, image_reader  # noqa: E402

from .test_phase3 import staff  # noqa: E402

TEXT_LIST = "لیست امروز\nA57 8/256 Black 159000\nRedmi 15C 8/256 66500-67000\nسلام"


def test_text_list_is_read_and_kept_once(db, settings, tmp_path):
    settings.pricelists_dir = str(tmp_path)
    out = channels.store(db, settings, channel="karimi", channel_title="کریمی", data=b"",
                         text=TEXT_LIST)
    assert out["outcome"] == "read" and out["rows"] == 2 and out["usable"] == 2
    again = channels.store(db, settings, channel="karimi", channel_title="کریمی", data=b"",
                           text=TEXT_LIST)
    assert again["outcome"] == "duplicate"
    item = channels.get(db, out["id"])
    assert item["rows"][1]["price_min"] == 66500 and item["rows"][1]["price_max"] == 67000
    assert channels.lists(db)[0]["channel_title"] == "کریمی"


def test_ranges_and_doubtful_rows():
    assert image_reader.parse_range("209000-210") == (209000, 210000)
    assert image_reader.parse_range("91000-91500") == (91000, 91500)
    words = [image_reader.Word("A57", 10, 100, 40, 14), image_reader.Word("8/256", 60, 100, 50, 14),
             image_reader.Word("BLACK", 130, 100, 50, 14), image_reader.Word("159000", 300, 100, 60, 14),
             image_reader.Word("A56", 10, 130, 40, 14), image_reader.Word("BLUE", 130, 130, 50, 14),
             image_reader.Word("A36", 10, 160, 40, 14), image_reader.Word("WHITE", 130, 160, 50, 14),
             image_reader.Word("99000", 300, 160, 60, 14), image_reader.Word("A37", 10, 190, 40, 14),
             image_reader.Word("GRAY", 130, 190, 50, 14), image_reader.Word("1O9000", 300, 190, 60, 14),
             image_reader.Word("REDMI", 10, 220, 50, 14), image_reader.Word("AS", 70, 220, 20, 14),
             image_reader.Word("GOLD", 130, 220, 50, 14), image_reader.Word("44900", 300, 220, 60, 14)]
    rows = image_reader.read_words(words)
    states = [(r.name, r.state) for r in rows]
    assert ("A57 8/256", "ok") in states and ("A36", "ok") in states
    assert ("A56", "doubtful") in states            # no price read (***)
    assert ("A37", "doubtful") in states            # «1O9000» is not a clean number
    assert ("REDMI AS", "doubtful") in states       # S / 5
    assert all(r.reasons for r in rows if r.state == "doubtful")   # always says why


def test_picture_list_needs_approval_and_basis_returns_by_itself(client, db, settings, tmp_path,
                                                                  monkeypatch):
    settings.pricelists_dir = str(tmp_path)
    rows = [image_reader.ImageRow(table=0, brand="XIAOMI", name="REDMI 15C 8/256", color="BLACK",
                                  price_min=66500, price_max=67000, box=(1, 2, 3, 4)),
            image_reader.ImageRow(table=0, name="POCO cn", state="doubtful", reasons=["x"])]
    monkeypatch.setattr(image_reader, "read_image", lambda path: rows)
    out = channels.store(db, settings, channel="karimi", channel_title="کریمی",
                         data=b"\x89PNG-fake-picture")
    assert out == {"outcome": "read", "id": out["id"], "rows": 2, "usable": 1}
    manager = staff(db)
    r = client.post("/admin/price-basis", json={"list_id": out["id"], "column": "max"},
                    headers=manager)
    assert r.status_code == 409 and "not approved" in r.json()["detail"]
    assert client.post(f"/admin/channel-lists/{out['id']}/approve",
                       headers=manager).status_code == 200
    r = client.post("/admin/price-basis", json={"list_id": out["id"], "column": "max"},
                    headers=manager)
    assert r.status_code == 200 and r.json()["basis"]["column"] == "max"
    listed, sold = purchase.active_rows(db, settings)
    assert listed["channel"] == "کریمی" and len(sold) == 1            # the doubtful row: never
    assert sold[0]["price_rial"] == 67000 * settings.pricelist_unit_rial
    assert sold[0]["mapping_id"] is None                               # only «درخواست خرید»
    # the time passes: the main list is the basis again by itself
    basis = channels.basis_state(db)
    later = datetime.fromisoformat(basis["until"]) + timedelta(seconds=1)
    assert channels.basis_state(db, later) is None
    assert channels.basis_state(db) is None
    assert client.get("/admin/channel-lists", headers=manager).json()["basis"] is None


def test_worker_posts_a_channel_file(client, db, settings, tmp_path):
    settings.pricelists_dir = str(tmp_path)
    settings.worker_api_key = "worker-key"
    r = client.post("/worker/channel-files", json={"channel": "brans", "title": "برنس",
                                                   "text": TEXT_LIST},
                    headers={"X-API-Key": "worker-key"})
    assert r.status_code == 200 and r.json()["usable"] == 2
