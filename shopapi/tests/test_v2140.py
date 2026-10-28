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
