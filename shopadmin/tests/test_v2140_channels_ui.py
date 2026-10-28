"""v2.14.0 «لیست کانال‌های دیگر»: approval before a picture list is the basis,
the basis text, the rows dialog with a cropped picture per row."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from app.ui import channel_lists as cl  # noqa: E402
from app.ui import widgets  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
       b"\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
       b"\x00\x00\x00\x00IEND\xaeB`\x82")


class FakeApi:
    def __init__(self):
        self.calls = []
        self.lists = [{"id": 1, "channel": "karimi", "channel_title": "کریمی", "kind": "image",
                       "status": "read", "total": 3, "usable": 2, "approved_at": None,
                       "is_basis": False, "created_at": "2026-10-28T08:00:00+00:00"}]

    def channel_lists(self):
        return {"lists": self.lists, "basis": None}

    def channel_list(self, list_id):
        return {**self.lists[0], "rows": [
            {"brand": "XIAOMI", "name": "REDMI 15C 8/256", "color": "BLACK", "price_min": 66500,
             "price_max": 67000, "state": "ok", "reasons": [], "box": [0, 0, 1, 1]},
            {"brand": "", "name": "POCO cn", "color": "", "price_min": None, "price_max": None,
             "state": "doubtful", "reasons": ["بخشی از نام نامطمئن خوانده شد"], "box": [0, 0, 1, 1]}]}

    def channel_row_crop(self, list_id, index):
        return PNG

    def approve_channel_list(self, list_id):
        self.calls.append(("approve", list_id))
        self.lists[0]["approved_at"] = "2026-10-28T09:00:00+00:00"
        return {}

    def set_price_basis(self, list_id, column, until=None):
        self.calls.append(("basis", list_id, column, until))
        return {}


class FakePage(widgets.QWidget):
    def __init__(self):
        super().__init__()
        self.context = SimpleNamespace(api=FakeApi())
        self.can_manage = True
        self.notes = []

    def run(self, fn, *, on_success, on_error=None, busy_message=""):
        on_success(fn())

    def notify_success(self, text):
        self.notes.append(text)


def test_picture_list_basis_only_after_approval(admin_qapp, monkeypatch):
    page = FakePage()
    panel = cl.ChannelListsPanel(page)
    panel.load()
    assert "ابریشمی" in panel.basis_label.text()
    panel.table.select_row(0)
    assert not panel.basis_button.isEnabled() and panel.approve_button.isEnabled()
    monkeypatch.setattr(cl.widgets, "confirm", lambda *a, **k: True)
    panel._approve()
    panel.table.select_row(0)
    assert panel.basis_button.isEnabled()
    monkeypatch.setattr(cl.BasisDialog, "exec", lambda self: True)
    panel._make_basis()
    assert page.context.api.calls[-1] == ("basis", 1, "min", None)     # = end of today


def test_rows_dialog_shows_crops_and_doubtful_reasons(admin_qapp):
    page = FakePage()
    dialog = cl.ChannelRowsDialog(page, page.context.api.channel_list(1))
    assert dialog.table.rowCount() == 2
    assert dialog.table.cellWidget(0, 0).pixmap() is not None
    assert "نامطمئن" in dialog.table.item(1, 5).text()


def test_basis_text():
    text = cl.basis_text({"list_id": 1, "column": "max", "until": "2026-10-28T20:29:59+00:00"},
                         [{"id": 1, "channel_title": "برنس"}])
    assert "برنس" in text and "قیمت زیاد" in text and "ابریشمی" in text
