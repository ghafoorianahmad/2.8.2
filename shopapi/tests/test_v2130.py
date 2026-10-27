"""v2.13.0: the 1405/08/05 price list (a sub-section with its own نقد/روال
header row) is read, a moved header still is a layout change, the PDF archive
(date + number, never deleted, reminders), «خواندن دوباره» and «دریافت لیست اکنون»."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.pricelist import parser
from app.pricelist.parser import ParseError, parse_pdf, parse_words

SAMPLE_0805 = Path(__file__).resolve().parents[2] / "samples" / "price_list_1405-08-05.pdf"


def _words(sub_header=None, rows=25):
    """Two blocks; ``sub_header`` = (x naghd, x raval, top) of a lower header pair."""
    words = [{"text": "1405/08/05", "x0": 450, "top": 20},
             {"text": "دقن", "x0": 150, "top": 40}, {"text": "لاور", "x0": 180, "top": 40},
             {"text": "دقن", "x0": 350, "top": 40}, {"text": "لاور", "x0": 380, "top": 40}]
    for i in range(rows):
        top = 52 + i * 11
        for base in (0, 200):
            words += [{"text": f"Model{base}{i}", "x0": base + 17, "top": top},
                      {"text": "تیکشر", "x0": base + 96, "top": top - 2},
                      {"text": "Black", "x0": base + 118, "top": top},
                      {"text": f"{100 + i},000", "x0": base + 145, "top": top - 1},
                      {"text": f"{101 + i},000", "x0": base + 174, "top": top - 1}]
    if sub_header:
        xn, xr, top = sub_header
        words += [{"text": "TABLET", "x0": 276, "top": top - 1},
                  {"text": "XIAOMI", "x0": 307, "top": top - 1},
                  {"text": "دقن", "x0": xn, "top": top}, {"text": "لاور", "x0": xr, "top": top}]
    return words


def test_sub_section_header_row_is_read():
    parsed = parse_words(_words(sub_header=(362, 389, 52 + 12 * 11 + 5)), 595)
    assert parsed.list_date == "1405/08/05"
    assert len(parsed.rows) == 50
    assert "TABLET XIAOMI" in parsed.sections
    # the rows below the sub-header belong to it
    below = [r for r in parsed.rows if r.block == 1 and r.top > 52 + 12 * 11 + 5]
    assert below and all(r.section == "TABLET XIAOMI" for r in below)


@pytest.mark.parametrize("sub_header", [
    (60, 389, 300),        # نقد far from the block's price column
    (362, 560, 300),       # the pair split over two blocks
])
def test_odd_lower_headers_are_still_a_layout_change(sub_header):
    with pytest.raises(ParseError, match="not on one line"):
        parse_words(_words(sub_header=sub_header), 595)


def test_a_single_lower_header_is_a_layout_change():
    words = _words() + [{"text": "دقن", "x0": 352, "top": 300}]
    with pytest.raises(ParseError, match="not on one line"):
        parse_words(words, 595)


@pytest.mark.skipif(not SAMPLE_0805.exists(), reason="samples/price_list_1405-08-05.pdf missing")
def test_real_list_of_1405_08_05():
    parsed = parse_pdf(SAMPLE_0805.read_bytes())
    assert parsed.list_date == "1405/08/05"
    assert len(parsed.rows) == 208
    assert parsed.warnings == []
    assert "TABLET XIAOMI" in parsed.sections
    pad = [r for r in parsed.rows if r.description == "Xiaomi Pad8 256GB Ram8"]
    assert pad and pad[0].section == "TABLET XIAOMI" and pad[0].naghd == 114500
    assert parser.decode_persian("تیکشر") == "شرکتی"


# ---- v2.13.0: archive, «خواندن دوباره», retry, «دریافت لیست اکنون», alerts ----------------
from datetime import datetime, timezone  # noqa: E402

from app.pricelist import importer, pdf_archive  # noqa: E402
from app.pricelist.repo import PriceListRepo  # noqa: E402
from app.routers import pricelist as pricelist_router  # noqa: E402

from .conftest import h  # noqa: E402
from .test_phase3 import _fake_list, staff  # noqa: E402

# 2026-10-27 08:00 UTC = 1405/08/05 in Tehran
WHEN = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)


def test_jalali_and_archive_names(tmp_path):
    assert pdf_archive.tehran_jalali(WHEN) == (1405, 8, 5)
    # 22:00 UTC = 01:30 the next day in Tehran
    assert pdf_archive.tehran_jalali(datetime(2026, 10, 27, 22, 0, tzinfo=timezone.utc)) == \
        (1405, 8, 6)
    assert pdf_archive.archive_name(tmp_path, WHEN) == "1405-08-05-1.pdf"
    (tmp_path / "1405-08-05-1.pdf").write_bytes(b"x")
    (tmp_path / "1405-08-05-3.pdf").write_bytes(b"x")
    (tmp_path / "1405-08-04-9.pdf").write_bytes(b"x")
    assert pdf_archive.archive_name(tmp_path, WHEN) == "1405-08-05-4.pdf"


def test_every_received_file_is_archived_never_twice(db, settings, tmp_path, monkeypatch):
    settings.pricelists_dir = str(tmp_path)
    monkeypatch.setattr(pdf_archive, "now_utc", lambda: WHEN)
    holder = {b"%PDF-A": _fake_list("1405/08/05"), b"%PDF-B": _fake_list("1405/08/01"),
              b"%PDF-C": parser.ParseError("price headers are not on one line")}

    def fake(data):
        value = holder[data]
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(importer, "parse_pdf", fake)
    outcomes = [importer.import_pdf(db, settings, d, source="manual").outcome
                for d in (b"%PDF-A", b"%PDF-B", b"%PDF-C", b"%PDF-A")]
    assert outcomes == ["active", "older", "failed", "duplicate"]
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["1405-08-05-1.pdf", "1405-08-05-2.pdf", "1405-08-05-3.pdf"]
    files = {r["status"]: r["file_name"] for r in PriceListRepo(db).list_lists()}
    assert files["failed"] == "1405-08-05-3.pdf"
    info = pdf_archive.archive_info(settings)
    assert info["files"] == 3 and info["path"] == str(tmp_path)


def test_reread_a_failed_list_imports_it_in_place(db, settings, tmp_path, monkeypatch):
    settings.pricelists_dir = str(tmp_path)
    state = {"fail": True}

    def fake(data):
        if state["fail"]:
            raise parser.ParseError("price headers are not on one line")
        return _fake_list("1405/08/05")
    monkeypatch.setattr(importer, "parse_pdf", fake)
    failed = importer.import_pdf(db, settings, b"%PDF-X", source="telegram")
    assert failed.outcome == "failed"
    assert [e["kind"] for e in db.list_events(0, 100)] == ["pricelist_failed"]
    # still unreadable: the reason is updated, no second alert
    again = importer.reread_list(db, settings, failed.list_id, actor="t")
    assert again.outcome == "failed"
    assert [e["kind"] for e in db.list_events(0, 100)] == ["pricelist_failed"]
    # the new reader: same record, now the active list
    state["fail"] = False
    done = importer.reread_list(db, settings, failed.list_id, actor="t")
    assert done.outcome == "active" and done.list_id == failed.list_id and done.row_count == 30
    plist = PriceListRepo(db).get_list(failed.list_id)
    assert plist["status"] == "active" and plist["list_date"] == "1405/08/05"
    # reading a good list again changes nothing
    assert importer.reread_list(db, settings, failed.list_id, actor="t").outcome == "read"


def test_same_failed_file_again_is_read_again(db, settings, tmp_path, monkeypatch):
    settings.pricelists_dir = str(tmp_path)
    state = {"fail": True}

    def fake(data):
        if state["fail"]:
            raise parser.ParseError("no date found")
        return _fake_list("1405/08/05")
    monkeypatch.setattr(importer, "parse_pdf", fake)
    first = importer.import_pdf(db, settings, b"%PDF-Y", source="telegram")
    state["fail"] = False
    second = importer.import_pdf(db, settings, b"%PDF-Y", source="telegram")
    assert second.outcome == "active" and second.list_id == first.list_id


def test_reread_without_a_stored_file(db, settings, monkeypatch):
    monkeypatch.setattr(importer, "parse_pdf", lambda d: _fake_list())
    result = importer.import_pdf(db, settings, b"%PDF-Z", source="manual")   # :memory: = no copy
    assert importer.reread_list(db, settings, result.list_id, actor="t").outcome == "missing"


def test_retry_recent_failed_runs_once_per_version(db, settings, tmp_path, monkeypatch):
    settings.pricelists_dir = str(tmp_path)
    state = {"fail": True}

    def fake(data):
        if state["fail"]:
            raise parser.ParseError("price headers are not on one line")
        return _fake_list("1405/08/05")
    monkeypatch.setattr(importer, "parse_pdf", fake)
    importer.import_pdf(db, settings, b"%PDF-R", source="telegram")
    state["fail"] = False
    results = importer.retry_recent_failed(db, settings, "2.13.0")
    assert [r.outcome for r in results] == ["active"]
    assert importer.retry_recent_failed(db, settings, "2.13.0") == []


def test_reread_and_fetch_endpoints(client, db, settings, tmp_path, monkeypatch):
    settings.pricelists_dir = str(tmp_path)
    monkeypatch.setattr(importer, "parse_pdf", lambda d: _fake_list())
    result = importer.import_pdf(db, settings, b"%PDF-E", source="manual")
    manager = staff(db)
    r = client.post(f"/admin/pricelists/{result.list_id}/reread", headers=manager)
    assert r.status_code == 200 and r.json()["outcome"] == "read"
    assert client.post("/admin/pricelists/999/reread", headers=manager).status_code == 404
    assert client.post(f"/admin/pricelists/{result.list_id}/reread",
                       headers=staff(db, "operator", "op")).status_code == 403
    # a file that keeps the reader busy: answered anyway
    monkeypatch.setattr(pricelist_router, "REREAD_TIMEOUT_SEC", 0.05)
    import time as _time
    monkeypatch.setattr(pricelist_router, "reread_list",
                        lambda *a, **k: _time.sleep(0.5))
    assert client.post(f"/admin/pricelists/{result.list_id}/reread",
                       headers=manager).json()["outcome"] == "timeout"
    # «دریافت لیست اکنون»: asked, then handled by the worker
    asked = client.post("/admin/pricelists/fetch", headers=manager).json()["requested_at"]
    assert client.get("/admin/pricelists/fetch", headers=manager).json() == \
        {"requested_at": asked, "handled": False}
    worker = {"X-API-Key": "worker-key"}
    settings.worker_api_key = "worker-key"
    assert client.get("/worker/state", headers=worker).json()["tg_price_request"] == asked
    client.put("/worker/state", json={"key": "tg_price_done", "value": asked}, headers=worker)
    assert client.get("/admin/pricelists/fetch", headers=manager).json()["handled"] is True


def test_archive_reminder_once_per_date(db, settings, tmp_path):
    settings.pricelists_dir = str(tmp_path)
    sent = []
    send = sent.append
    # first check after the upgrade (1405/08/05): only notes the quarter
    assert not pdf_archive.check_reminder(db, settings, WHEN, sender=send)
    assert pdf_archive.check_reminder(db, settings, WHEN, sender=send) is False
    # 1 Dey 1405 = 2026-12-22
    dey = datetime(2026, 12, 22, 6, 0, tzinfo=timezone.utc)
    assert pdf_archive.current_slot(dey) == "1405-10"
    assert pdf_archive.check_reminder(db, settings, dey, sender=send) is True
    assert pdf_archive.check_reminder(db, settings, dey, sender=send) is False
    # 1 Farvardin 1406 = 2027-03-21
    nowruz = datetime(2027, 3, 21, 6, 0, tzinfo=timezone.utc)
    assert pdf_archive.check_reminder(db, settings, nowruz, sender=send) is True
    assert len(sent) == 2 and "سال نو" in sent[1]
    kinds = [e["kind"] for e in db.list_events(0, 100)]
    assert kinds.count("pricelist_archive_reminder") == 2


def test_new_worker_alerts_go_to_bale_once(client, db, settings, monkeypatch):
    settings.worker_api_key = "worker-key"
    sent = []
    monkeypatch.setattr(pricelist_router.owner_alerts, "send_owner_alert",
                        lambda text: sent.append(text))
    worker = {"X-API-Key": "worker-key"}
    body = {"kind": "worker_restarted", "detail": "کارگر تلگرام"}
    assert client.post("/worker/alerts", json=body, headers=worker).json()["sent"] is True
    assert client.post("/worker/alerts", json=body, headers=worker).json()["sent"] is False
    assert len(sent) == 1 and "کارگر تلگرام" in sent[0]
    assert client.post("/worker/alerts", json={"kind": "telegram_flood_wait"},
                       headers=worker).json()["sent"] is True
    assert len(sent) == 2


def test_server_status_shows_the_archive_and_backup_reason(client, db, settings, tmp_path,
                                                           monkeypatch):
    from app import control

    settings.pricelists_dir = str(tmp_path)
    (tmp_path / "1405-08-05-1.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(control, "backup_status", lambda: {
        "at": "2026-10-27T03:00:00+03:30", "ok": False, "local_ok": True,
        "error": "off-server copy failed",
        "offsite": {"configured": True, "ok": False, "network": True,
                    "error": "PermissionError: Access is denied (network share: no user name for it)"}})
    status = client.get("/admin/server/status", headers=staff(db, "super_admin", "boss")).json()
    assert status["pricelist_archive"]["files"] == 1
    backup = status["backup"]
    assert backup["local_ok"] is True and "نام کاربری" in backup["offsite_reason_fa"]


def test_backup_test_explains_a_network_share_without_user(monkeypatch):
    from app.routers import server_admin

    import contextlib

    def denied(*a, **k):
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(server_admin, "_share_session",
                        lambda *a: contextlib.nullcontext(False))
    monkeypatch.setattr("pathlib.Path.mkdir", denied)
    result = server_admin.check_backup_folder(r"\\192.168.20.150\E\ShopServerBackup")
    assert result["ok"] is False and "نام کاربری" in result["message_fa"]
