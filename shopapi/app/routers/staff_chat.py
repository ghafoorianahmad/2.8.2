"""v2.18.0 «گفت‌وگوی همکاران»: public and private chat between staff, text and voice.

Everything stays in this server's own database and data folder: it goes through ShopServer on
the shop's network, and nothing is ever relayed to Bale or Telegram. A signed-in staff session
is required (never an API key), with its own tick. A private room is only for its two members.
"""
from __future__ import annotations

import base64
import binascii
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .. import deps
from ..config import Settings
from ..db_own import OwnDB
from ..security import Identity, require_permission
from ..staff import P_STAFF_CHAT_SEND, P_STAFF_CHAT_VIEW
from ..util import now_iso

logger = logging.getLogger("shopapi.staff_chat")
router = APIRouter(prefix="/admin/chat")

PUBLIC_ROOM = "public"
_DM = re.compile(r"^dm:(\d+):(\d+)$")
MAX_TEXT = 2000
MAX_VOICE_BYTES = 10 * 1024 * 1024
#: what a recording may be
VOICE_TYPES = {"audio/mp4": ".m4a", "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/wav": ".wav",
               "audio/x-wav": ".wav", "audio/webm": ".webm"}

CAN_VIEW = Depends(require_permission(P_STAFF_CHAT_VIEW))
CAN_SEND = Depends(require_permission(P_STAFF_CHAT_SEND))


class TextIn(BaseModel):
    room: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class VoiceIn(BaseModel):
    room: str = Field(min_length=1, max_length=40)
    seconds: int = Field(default=0, ge=0, le=3600)
    content_type: str = Field(default="audio/wav", max_length=40)
    #: a little over MAX_VOICE_BYTES once in base64, as the price list PDFs travel
    data_b64: str = Field(min_length=1, max_length=MAX_VOICE_BYTES * 4 // 3 + 8)


def dm_room(a: int, b: int) -> str:
    low, high = sorted((int(a), int(b)))
    return f"dm:{low}:{high}"


def _me(who: Identity) -> int:
    if who.kind != "staff" or who.user_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "این بخش فقط برای همکارانی است که وارد شده‌اند.")
    return int(who.user_id)


def _check_room(room: str, me: int, db: OwnDB) -> None:
    """Only the two members may even know a private room exists."""
    if room == PUBLIC_ROOM:
        return
    match = _DM.match(room)
    members = {int(match.group(1)), int(match.group(2))} if match else set()
    if me not in members or len(members) != 2 or room != dm_room(*members):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "این گفت‌وگو پیدا نشد.")
    other = (members - {me}).pop()
    if db.get_staff(other) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "این گفت‌وگو پیدا نشد.")


def _unread(db: OwnDB, room: str, me: int) -> int:
    row = db._fetchone(
        "SELECT COUNT(*) AS n FROM staff_chat_messages m WHERE m.room=? AND m.sender_id<>? AND m.id>"
        "COALESCE((SELECT last_id FROM staff_chat_reads r WHERE r.room=? AND r.staff_id=?),0)",
        (room, me, room, me))
    return int(row["n"]) if row else 0


def _out(row: dict, me: int) -> dict:
    return {"id": row["id"], "room": row["room"], "mine": row["sender_id"] == me,
            "sender_name": row["sender_name"], "text": row["text"],
            "voice": bool(row["voice_file"]), "voice_seconds": row["voice_seconds"],
            "created_at": row["created_at"]}


@router.get("/rooms")
def rooms(db: OwnDB = Depends(deps.get_db), who: Identity = CAN_VIEW) -> dict:
    """The public room and one private room per colleague, each with its unread count."""
    me = _me(who)
    with db._lock:
        out = [{"room": PUBLIC_ROOM, "name": "گفت‌وگوی عمومی", "unread": _unread(db, PUBLIC_ROOM, me)}]
        for person in db.list_staff():
            if int(person["id"]) == me or not person.get("active", 1):
                continue
            room = dm_room(me, person["id"])
            out.append({"room": room, "name": person.get("full_name") or person.get("username"),
                        "unread": _unread(db, room, me)})
    return {"rooms": out, "unread": sum(r["unread"] for r in out)}


@router.get("/messages")
def messages(room: str = Query(max_length=40), after: int = Query(0, ge=0),
             db: OwnDB = Depends(deps.get_db), who: Identity = CAN_VIEW) -> list[dict]:
    """Newer than ``after``, oldest first. Reading marks the room as read."""
    me = _me(who)
    _check_room(room, me, db)
    with db._lock:
        rows = db._fetchall(
            "SELECT * FROM (SELECT * FROM staff_chat_messages WHERE room=? AND id>? "
            "ORDER BY id DESC LIMIT 200) ORDER BY id", (room, int(after)))
        if rows:
            db._conn.execute(
                "INSERT INTO staff_chat_reads (room, staff_id, last_id) VALUES (?,?,?) "
                "ON CONFLICT(room, staff_id) DO UPDATE SET last_id=MAX(last_id, excluded.last_id)",
                (room, me, rows[-1]["id"]))
            db._commit()
    return [_out(row, me) for row in rows]


def _insert(db: OwnDB, room: str, who: Identity, text: str, voice_file: str = "",
            seconds: int = 0) -> dict:
    person = db.get_staff(int(who.user_id)) or {}
    sender = str(person.get("full_name") or person.get("username") or who.username)
    with db._lock:
        cur = db._conn.execute(
            "INSERT INTO staff_chat_messages (room, sender_id, sender_name, text, voice_file, "
            "voice_seconds, created_at) VALUES (?,?,?,?,?,?,?)",
            (room, int(who.user_id), sender, text, voice_file, int(seconds), now_iso()))
        db._commit()
        return db._fetchone("SELECT * FROM staff_chat_messages WHERE id=?", (cur.lastrowid,))


@router.post("/messages", status_code=status.HTTP_201_CREATED)
def send_text(payload: TextIn, db: OwnDB = Depends(deps.get_db), who: Identity = CAN_SEND) -> dict:
    me = _me(who)
    _check_room(payload.room, me, db)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "پیام خالی است.")
    return _out(_insert(db, payload.room, who, text), me)


def _voice_dir(settings: Settings) -> Path:
    """Beside the receipts (not in a backup-less temp folder)."""
    receipts = settings.receipts_path()
    if receipts is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "پوشهٔ دادهٔ سرور پیدا نشد.")
    folder = receipts.parent / "staff_voice"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@router.post("/voice", status_code=status.HTTP_201_CREATED)
def send_voice(
    payload: VoiceIn,
    db: OwnDB = Depends(deps.get_db),
    settings: Settings = Depends(deps.get_settings),
    who: Identity = CAN_SEND,
) -> dict:
    """A recording. Only stored and handed back: the server never plays or opens it."""
    me = _me(who)
    _check_room(payload.room, me, db)
    suffix = VOICE_TYPES.get(payload.content_type.strip().lower())
    if suffix is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "این نوع صدا پذیرفته نمی‌شود.")
    try:
        body = base64.b64decode(payload.data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "پیام صوتی خراب است.") from None
    if not body or len(body) > MAX_VOICE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "پیام صوتی خالی یا بیش از اندازه است.")
    folder = _voice_dir(settings)
    row = _insert(db, payload.room, who, "", f"pending{suffix}", payload.seconds)
    name = f"{row['id']}{suffix}"
    (folder / name).write_bytes(body)
    with db._lock:
        db._conn.execute("UPDATE staff_chat_messages SET voice_file=? WHERE id=?", (name, row["id"]))
        db._commit()
    row["voice_file"] = name
    return _out(row, me)


@router.get("/voice/{message_id}")
def get_voice(message_id: int, db: OwnDB = Depends(deps.get_db),
              settings: Settings = Depends(deps.get_settings),
              who: Identity = CAN_VIEW) -> dict:
    me = _me(who)
    with db._lock:
        row = db._fetchone("SELECT * FROM staff_chat_messages WHERE id=?", (int(message_id),))
    if row is None or not row["voice_file"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "پیدا نشد.")
    _check_room(row["room"], me, db)
    # the name comes from our own insert, never from a request
    path = _voice_dir(settings) / Path(row["voice_file"]).name
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "پیدا نشد.")
    return {"data_b64": base64.b64encode(path.read_bytes()).decode("ascii")}
