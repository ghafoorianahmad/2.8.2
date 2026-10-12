"""Fake Telethon client + fake proxy pool for the Telegram channel tests (no network)."""
from __future__ import annotations

from types import SimpleNamespace

from telethon import events


class AccessTokenInvalidError(Exception):
    """Same class name as Telethon's, which the adapter treats as fatal."""


class FakeWorld:
    """Shared state of the fake 'Telegram': which proxies work, what was sent."""

    def __init__(self):
        self.dead: set[tuple[str, int]] = set()        # (host, port) that refuse to connect
        self.direct_works = True
        self.ping_fails = False
        self.bad_token = False
        self.authorized = False
        self.clients: list[FakeClient] = []
        self.sent: list[dict] = []
        self.edited: list[dict] = []
        self.files: list[dict] = []
        self.signed_in = 0
        self._mid = 1000

    def factory(self, session, api_id, api_hash, **kwargs):
        client = FakeClient(self, session, api_id, api_hash, kwargs)
        self.clients.append(client)
        return client

    def next_id(self) -> int:
        self._mid += 1
        return self._mid

    # ---- the outside world talking to the bot ------------------------------
    @property
    def live(self) -> "FakeClient":
        return [c for c in self.clients if c.connected][-1]

    async def user_says(self, *, user_id, text="", contact=None, photo=False, document=None,
                        first_name="Ali", last_name="Rezaei", is_private=True, bot=False,
                        data=None, size=2048):
        sender = SimpleNamespace(id=user_id, first_name=first_name, last_name=last_name,
                                 username=None, bot=bot)
        mid = self.next_id()
        file = None
        if photo:
            file = SimpleNamespace(size=size, mime_type="image/jpeg", name=None)
        if document:
            file = SimpleNamespace(size=document.get("size", size),
                                   mime_type=document.get("mime_type"), name=document.get("name"))
        blob = data if data is not None else b"\xff\xd8\xff\xe0" + b"0" * 64
        msg = SimpleNamespace(
            id=mid, message=text, contact=contact, file=file,
            photo=object() if photo else None,
            document=object() if document else None,
            media=SimpleNamespace(blob=blob) if file else None)

        async def get_sender():
            return sender
        event = SimpleNamespace(message=msg, chat_id=user_id, sender_id=user_id,
                                is_private=is_private, get_sender=get_sender)
        await self.live.dispatch(events.NewMessage, event)

    async def user_presses(self, *, user_id, data: str, qid=None):
        answers: list[dict] = []

        async def answer(text=None, alert=False):
            answers.append({"text": text, "alert": alert})
        qid = qid or self.next_id()
        event = SimpleNamespace(data=data.encode(), query=SimpleNamespace(query_id=qid),
                                message_id=self.next_id(), chat_id=user_id, is_private=True,
                                answer=answer)
        await self.live.dispatch(events.CallbackQuery, event)
        return answers


class FakeClient:
    def __init__(self, world: FakeWorld, session, api_id, api_hash, kwargs):
        self.world = world
        self.session = session
        self.kwargs = kwargs
        self.proxy = kwargs.get("proxy")
        self.connection = kwargs.get("connection")
        self.connected = False
        self.parse_mode = "md"
        self.handlers: list[tuple] = []

    async def connect(self):
        if self.proxy is None:
            if not self.world.direct_works:
                raise ConnectionError("direct blocked")
        elif (self.proxy[0], self.proxy[1]) in self.world.dead:
            raise ConnectionError("proxy dead")
        self.connected = True

    def is_connected(self):
        return self.connected

    async def is_user_authorized(self):
        return self.world.authorized

    async def sign_in(self, bot_token=None):
        if self.world.bad_token:
            raise AccessTokenInvalidError()
        self.world.signed_in += 1
        self.world.authorized = True

    async def disconnect(self):
        self.connected = False

    def add_event_handler(self, callback, event):
        self.handlers.append((callback, event))

    async def dispatch(self, kind, event):
        for callback, builder in self.handlers:
            if isinstance(builder, kind):
                await callback(event)

    async def __call__(self, request):
        if self.world.ping_fails:
            raise ConnectionError("ping failed")
        return SimpleNamespace()

    async def send_message(self, chat, text, buttons=None, link_preview=None):
        record = {"chat": chat, "text": text, "buttons": buttons, "id": self.world.next_id(),
                  "seq": self.world.next_id()}
        self.world.sent.append(record)
        return SimpleNamespace(id=record["id"])

    async def edit_message(self, chat, message_id, text, buttons=None, link_preview=None):
        self.world.edited.append({"chat": chat, "id": message_id, "text": text, "buttons": buttons,
                                  "seq": self.world.next_id()})
        return SimpleNamespace(id=message_id)

    async def send_file(self, chat, media, caption="", buttons=None):
        record = {"chat": chat, "media": media, "caption": caption, "buttons": buttons,
                  "id": self.world.next_id()}
        self.world.files.append(record)
        return SimpleNamespace(id=record["id"])

    async def get_messages(self, chat, ids=None):
        return None

    async def iter_download(self, media):
        data = media.blob
        for i in range(0, len(data), 1024):
            yield data[i:i + 1024]


class FakePool:
    """Stands in for ProxyPool: a fixed candidate list, records the reports."""

    def __init__(self, candidates):
        self._candidates = list(candidates)
        self.reports: list[list[dict]] = []
        self.closed = False

    async def candidates(self):
        return list(self._candidates)

    async def report(self, results):
        self.reports.append(list(results))

    async def aclose(self):
        self.closed = True
