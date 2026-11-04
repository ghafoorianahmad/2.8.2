"""v2.18.2: the wheel, thousands separators, the installments page, the previous-years ledger."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QComboBox, QScrollBar, QSlider, QSpinBox, QTabBar, QWidget

from app.statuses import ROLE_OPERATOR, ROLE_SUPER_ADMIN
from app.ui.pages.installments import InstallmentsPage
from app.ui.wheel_guard import _WheelGuard, install_wheel_guard
from app.ui.widgets import AmountEdit
from tests.test_ui import make_context_with_role, ui_context  # noqa: F401 - fixture


def _wheel(widget: QWidget) -> QWheelEvent:
    event = QWheelEvent(QPointF(5, 5), QPointF(widget.mapToGlobal(QPoint(5, 5))), QPoint(0, 0),
                        QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    event.setAccepted(True)
    return event


def test_the_wheel_is_ignored_unless_the_control_has_focus(admin_qapp):
    install_wheel_guard(admin_qapp)
    spin, combo = QSpinBox(), QComboBox()
    spin.setRange(0, 9)
    spin.setValue(5)
    combo.addItems(["الف", "ب", "پ"])
    combo.setCurrentIndex(1)
    for widget in (spin, combo):
        event = _wheel(widget)
        admin_qapp.sendEvent(widget, event)
        assert not event.isAccepted()        # so it goes on to the scroll area
    assert spin.value() == 5 and combo.currentIndex() == 1


def test_a_clicked_control_takes_the_wheel_and_a_scroll_bar_always_does():
    guard = _WheelGuard()

    class Focused(QSpinBox):
        def hasFocus(self):  # noqa: N802 - Qt naming
            return True

    assert guard.eventFilter(Focused(), _wheel(QSpinBox())) is False
    assert guard.eventFilter(QScrollBar(), _wheel(QSpinBox())) is False
    for widget in (QSpinBox(), QComboBox(), QSlider(), QTabBar()):
        assert guard.eventFilter(widget, _wheel(widget)) is True


def test_the_wheel_gives_these_controls_no_focus(admin_qapp):
    install_wheel_guard(admin_qapp)
    spin, combo = QSpinBox(), QComboBox()
    for widget in (spin, combo):
        widget.ensurePolished()
        assert widget.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_amounts_are_grouped_while_typing(admin_qapp):
    box = AmountEdit()
    box.setFocus()
    box.setText("1000000000")
    assert box.text() == "۱٬۰۰۰٬۰۰۰٬۰۰۰"
    for typed in ("۵۰٪", "چند", ""):
        box.setText(typed)
        assert box.text() == typed                # not digits: stays as it is
    box.clear()
    box.insert("1234")
    box._regroup(box.text())
    assert box.text() == "۱٬۲۳۴" and box.cursorPosition() == len("۱٬۲۳۴")
    box.setCursorPosition(1)                      # after the first digit
    box.insert("9")
    box._regroup(box.text())
    assert box.text() == "۱۹٬۲۳۴" and box.cursorPosition() == 2


def test_every_amount_on_the_installments_page_groups(ui_context, admin_qapp):
    page = InstallmentsPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    page.price.setText("200000000")
    page.down_input.setText("100000000")
    assert page.down_input.text() == "۱۰۰٬۰۰۰٬۰۰۰"
    assert page.quote is not None and page.down == 100_000_000
    delegate = page.schedule.itemDelegateForColumn(2)
    assert isinstance(delegate.createEditor(page.schedule, None, None), AmountEdit)
    page.down_input.setText("۵۰٪")
    assert page.down == 100_000_000
    page.close()


def test_the_change_tick_alone_opens_the_rate_and_the_amounts(ui_context, admin_qapp):
    from app.permissions import INSTALLMENT_EDIT

    context = make_context_with_role(ui_context, ROLE_OPERATOR)
    plain = InstallmentsPage(context)
    assert plain.rate.isReadOnly() and plain.down_edit.isReadOnly() and plain.grand_edit.isReadOnly()
    plain.close()
    context.can = lambda key: key == INSTALLMENT_EDIT   # the rules tick is not given
    editing = InstallmentsPage(context)
    assert not editing.rate.isReadOnly() and not editing.total_edit.isReadOnly()
    assert not editing.reset_button.isHidden() and not editing.round_button.isHidden()
    assert editing.save_rate_button is None
    editing.close()


def test_the_comparison_is_last(ui_context, admin_qapp):
    page = InstallmentsPage(make_context_with_role(ui_context, ROLE_SUPER_ADMIN))
    last = page.column.itemAt(page.column.count() - 2).widget()
    assert page.compare in last.findChildren(type(page.compare))
    page.close()


class _LedgerApi:
    def __init__(self):
        self.statements = []

    def ledger_databases(self):
        return [{"name": "hesab5 t", "current": True}, {"name": "hesab4", "current": False}]

    def ledger_persons(self, database, query=""):
        return {"total": 1, "items": [{"code": 7, "name": "علی", "national_code": "••••••••78",
                                       "phone_tail": "67"}]}

    def ledger_statement(self, database, code):
        self.statements.append((database, code))
        return {"database": database, "balance": 100, "side": "debtor", "rows": [
            {"date": "1404/01/02", "kind": "سند", "doc_no": "9", "description": "x", "debit": 100,
             "credit": 0, "balance": 100, "side": "debtor"}]}


def test_the_ledger_page_prefers_a_previous_year_and_shows_a_turnover(ui_context, admin_qapp):
    from app.ui.pages.ledger import LedgerPage

    context = make_context_with_role(ui_context, ROLE_SUPER_ADMIN)
    page = LedgerPage(context)
    api = _LedgerApi()
    page.database.blockSignals(True)
    page._got_databases(api.ledger_databases())
    page.database.blockSignals(False)
    assert page.database.currentData() == "hesab4"
    assert page.database.itemText(0).endswith("(سال جاری)")
    page._got_persons(api.ledger_persons("hesab4"))
    assert page.person_table.item(0, 2).text().endswith("••••••••۷۸")
    page._shown_code = 7
    page._got_statement({"name": "علی"}, 7, api.ledger_statement("hesab4", 7))
    assert page.row_table.rowCount() == 1 and "بدهکار" in page.summary.text()
    page._shown_code = 8                       # a late answer for someone else is dropped
    page._got_statement({"name": "x"}, 7, {"rows": []})
    assert page.row_table.rowCount() == 1
    page.close()


def test_the_ledger_has_its_own_tick_and_only_a_view():
    from app import permissions as perms
    from app.ui.main_window import NAV_ITEMS

    assert "ledger.view" in perms.SECTION_PERMISSIONS and "ledger.edit" not in perms.SECTION_PERMISSIONS
    assert "ledger.view" not in perms.SALES_SERVER_PERMISSIONS
    assert perms.LEDGER_VIEW in perms.client_permissions({"ledger.view"})
    assert any(item[0] == "ledger" for item in NAV_ITEMS)
