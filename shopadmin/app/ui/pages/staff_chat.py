"""v2.18.0 «گفت‌وگوی همکاران»: عمومی و خصوصی، متن و صدا.

همه‌چیز از راه ShopServer در شبکهٔ فروشگاه می‌گذرد؛ هیچ پیامی به بله یا تلگرام نمی‌رود.
دیدن و فرستادن هر کدام تیک جدا دارد.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import voice
from ...permissions import STAFF_CHAT_SEND
from ...persian import format_datetime_shamsi, to_persian_digits
from .. import theme, widgets
from ..async_utils import run_async
from ..base_page import BasePage

#: how often the open room and the unread counts are read
POLL_MS = 4000


def room_title(room: dict) -> str:
    unread = int(room.get("unread") or 0)
    name = str(room.get("name") or "")
    return f"{name} ({to_persian_digits(unread)})" if unread else name


class StaffChatPage(BasePage):
    title = "گفت‌وگوی همکاران"
    subtitle = "عمومی و خصوصی، متن و پیام صوتی؛ فقط در شبکهٔ فروشگاه"
    help_text = ("پیام‌ها فقط از راه سرور فروشگاه می‌گذرند و به بله یا تلگرام نمی‌روند. برای "
                 "گفت‌وگوی خصوصی نام همکار را از فهرست انتخاب کنید.")
    reload_on_data_change = False

    def build_body(self) -> None:
        self.can_send = self.context.can(STAFF_CHAT_SEND)
        self.room: Optional[str] = None
        self.last_id = 0
        self.recorder = voice.Recorder()

        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        rooms_panel = widgets.Panel("گفت‌وگوها")
        self.rooms = QListWidget()
        self.rooms.setMinimumWidth(220)
        self.rooms.currentItemChanged.connect(self._room_changed)
        rooms_panel.body.addWidget(self.rooms, 1)
        row.addWidget(rooms_panel)

        chat_panel = widgets.Panel()
        self.room_label = widgets.label("گفت‌وگویی را انتخاب کنید", name="SectionTitle")
        chat_panel.body.addWidget(self.room_label)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.messages_holder = QWidget()
        self.messages_box = QVBoxLayout(self.messages_holder)
        self.messages_box.setContentsMargins(4, 4, 4, 4)
        self.messages_box.setSpacing(8)
        self.messages_box.addStretch(1)
        self.scroll.setWidget(self.messages_holder)
        self.scroll.setMinimumHeight(360)
        chat_panel.body.addWidget(self.scroll, 1)

        send_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("پیام خود را بنویسید…")
        self.input.setMaxLength(2000)
        self.input.returnPressed.connect(self._send_text)
        send_row.addWidget(self.input, 1)
        self.send_button = widgets.button("فرستادن", icon_name="check", variant="primary",
                                          on_click=self._send_text)
        send_row.addWidget(self.send_button)
        self.record_button = widgets.button("ضبط صدا", icon_name="mic",
                                            on_click=self._toggle_record)
        send_row.addWidget(self.record_button)
        self.cancel_record_button = widgets.button("لغو ضبط", on_click=self._cancel_record)
        self.cancel_record_button.setVisible(False)
        send_row.addWidget(self.cancel_record_button)
        chat_panel.body.addLayout(send_row)
        self.status_label = widgets.label("", name="Muted", wrap=True)
        self.status_label.setVisible(False)
        chat_panel.body.addWidget(self.status_label)
        for widget in (self.input, self.send_button, self.record_button):
            widget.setVisible(self.can_send)
        row.addWidget(chat_panel, 1)
        self.body.addWidget(holder, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self._tick)

    # ---- data ----------------------------------------------------------------------------
    def load(self) -> None:
        self.run(self.context.api.chat_rooms, on_success=self._rooms_loaded,
                 on_error=self.default_error)
        if not self.timer.isActive():
            self.timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        if not self.isVisible():
            self.timer.stop()
            return
        if self.recorder.recording:
            self._show_status(f"در حال ضبط… {to_persian_digits(self.recorder.elapsed())} ثانیه")
            if self.recorder.elapsed() >= voice.MAX_SECONDS:
                self._stop_record()
        self.run(self.context.api.chat_rooms, on_success=self._rooms_loaded, on_error=lambda *_: None)
        self._read_new()

    def _rooms_loaded(self, data: object) -> None:
        rooms = (data if isinstance(data, dict) else {}).get("rooms") or []
        self.rooms.blockSignals(True)
        try:
            self.rooms.clear()
            for room in rooms:
                item = QListWidgetItem(room_title(room))
                item.setData(Qt.ItemDataRole.UserRole, room.get("room"))
                self.rooms.addItem(item)
                if room.get("room") == self.room:
                    self.rooms.setCurrentItem(item)
        finally:
            self.rooms.blockSignals(False)
        if self.room is None and self.rooms.count():
            self.rooms.setCurrentRow(0)

    def _room_changed(self, item: Optional[QListWidgetItem], _old=None) -> None:
        if item is None:
            return
        self.room = str(item.data(Qt.ItemDataRole.UserRole))
        self.room_label.setText(item.text().split(" (")[0])
        self.last_id = 0
        while self.messages_box.count() > 1:
            taken = self.messages_box.takeAt(0)
            if taken.widget() is not None:
                taken.widget().deleteLater()
        self._read_new()

    def _read_new(self) -> None:
        room, after = self.room, self.last_id
        if room is None:
            return
        self.run(lambda: self.context.api.chat_messages(room, after),
                 on_success=lambda rows: self._messages_loaded(room, rows),
                 on_error=lambda *_: None)

    def _messages_loaded(self, room: str, rows: object) -> None:
        if room != self.room or not isinstance(rows, list):
            return
        for message in rows:
            message_id = int(message.get("id") or 0)
            if message_id <= self.last_id:
                continue
            self.last_id = message_id
            self.messages_box.insertWidget(self.messages_box.count() - 1, self._bubble(message))
        if rows:
            bar = self.scroll.verticalScrollBar()
            QTimer.singleShot(30, lambda: bar.setValue(bar.maximum()))

    def _bubble(self, message: dict) -> QWidget:
        frame = QFrame()
        frame.setObjectName("ChatBubble")
        mine = bool(message.get("mine"))
        frame.setStyleSheet(
            f"QFrame#ChatBubble {{ background: {theme.PRIMARY_SOFT if mine else theme.BACKGROUND}; "
            f"border: 1px solid {theme.BORDER}; border-radius: {theme.RADIUS}px; }}")
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(4)
        head = f"{message.get('sender_name') or ''} — {format_datetime_shamsi(message.get('created_at'))}"
        box.addWidget(widgets.label(head, name="Muted"))
        if message.get("voice"):
            seconds = to_persian_digits(message.get("voice_seconds") or 0)
            box.addWidget(widgets.button(f"پخش پیام صوتی ({seconds} ثانیه)", icon_name="mic",
                                         on_click=lambda m=int(message["id"]): self._play(m)))
        else:
            box.addWidget(widgets.label(str(message.get("text") or ""), wrap=True))
        return frame

    # ---- sending -------------------------------------------------------------------------
    def _send_text(self) -> None:
        text = self.input.text().strip()
        room = self.room
        if not text or room is None:
            return
        self.input.clear()
        self.run(lambda: self.context.api.chat_send(room, text),
                 on_success=lambda _r: self._read_new(), on_error=self.default_error)

    def _show_status(self, text: str, *, bad: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {theme.DANGER if bad else theme.TEXT_MUTED};")
        self.status_label.setVisible(bool(text))

    def _toggle_record(self) -> None:
        if self.recorder.recording:
            self._stop_record()
            return
        if self.room is None:
            return
        try:
            self.recorder.start()
        except voice.VoiceError as exc:
            self._show_status(str(exc), bad=True)
            return
        self.record_button.setText("پایان و فرستادن")
        self.cancel_record_button.setVisible(True)
        self._show_status("در حال ضبط…")

    def _stop_record(self) -> None:
        room = self.room
        self.record_button.setText("ضبط صدا")
        self.cancel_record_button.setVisible(False)
        try:
            data, seconds = self.recorder.stop()
        except (voice.VoiceError, OSError) as exc:
            self._show_status(str(exc) if isinstance(exc, voice.VoiceError)
                              else "ضبط ذخیره نشد.", bad=True)
            return
        self._show_status("")
        if room is None:
            return
        self.run(lambda: self.context.api.chat_send_voice(room, data, seconds),
                 on_success=lambda _r: self._read_new(), on_error=self.default_error)

    def _cancel_record(self) -> None:
        self.recorder.cancel()
        self.record_button.setText("ضبط صدا")
        self.cancel_record_button.setVisible(False)
        self._show_status("")

    def _play(self, message_id: int) -> None:
        run_async(lambda: self.context.api.chat_voice(message_id), on_success=self._play_bytes,
                  on_error=self.default_error)

    def _play_bytes(self, data: object) -> None:
        try:
            voice.play(bytes(data))
        except (voice.VoiceError, TypeError) as exc:
            self._show_status(str(exc) if isinstance(exc, voice.VoiceError)
                              else "این پیام صوتی پخش نشد.", bad=True)
