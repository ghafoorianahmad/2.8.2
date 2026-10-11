r"""Live Bale checks for REQUIREMENTS §3/§7 with a separate TEST bot.

(a) Does Bale pass the /start parameter of a deep link to the bot?
(b) Does a shared contact (request_contact button) carry ``contact.user_id``,
    and does it equal ``from.id``? (registration refuses contacts without it)

Use ONLY a separate Bale TEST bot - never the shop's real bot while ShopServer
is polling it (two pollers steal each other's updates).

    .\.venv\Scripts\python.exe scripts\check_start_param.py
    .\.venv\Scripts\python.exe scripts\check_start_param.py --formats   # try link variants

BALE_TEST_TOKEN (fallback: BALE_TOKEN) is read from the environment or shopbots/.env. The token
and the shared phone number are never printed or logged (only field names and
whether the ids match).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

API_BASE = os.environ.get("BALE_API_BASE", "https://tapi.bale.ai").rstrip("/")
PARAM = "kala_289"
WAIT_SECONDS = 900


def call(client: httpx.Client, token: str, method: str, payload: dict | None = None):
    try:
        response = client.post(f"{API_BASE}/bot{token}/{method}", json=payload or {})
    except httpx.HTTPError as exc:  # never show the URL: it contains the token
        sys.exit(f"{method}: network error ({type(exc).__name__})")
    data = response.json() if response.content else {}
    if not data.get("ok"):
        sys.exit(f"{method}: HTTP {response.status_code} {data.get('description', '')}")
    return data.get("result")


def wait_for(client, token, offset, accept):
    """Poll until ``accept(message)`` returns True; return (message, offset)."""
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        payload = {"timeout": 25, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        for update in call(client, token, "getUpdates", payload) or []:
            offset = update["update_id"] + 1
            message = update.get("message") or {}
            if accept(message):
                call(client, token, "getUpdates", {"offset": offset, "timeout": 0})
                return message, offset
    return None, offset


# Link variants for --formats: label -> start parameter.
VARIANTS = {
    "A underscore": "kala_289",
    "B letters+digits": "kala289",
    "C upper case": "KALA289",
    "D digits only": "289",
    "E encoded underscore": "kala%5F289",
}


def formats(client, token, username, offset) -> None:
    """Print several deep-link variants and report what each /start carried."""
    print("Open these links in Bale one after the other (press Start / شروع if asked).")
    print("Send the word  done  to the bot when finished.")
    for label, param in VARIANTS.items():
        print(f"  {label}:  https://ble.ir/{username}?start={param}", flush=True)
    seen = []
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        message, offset = wait_for(client, token, offset, lambda m: bool(m.get("text")))
        if message is None:
            break
        text = str(message.get("text") or "").strip()
        if text.lower() == "done":
            break
        if text.startswith("/start"):
            seen.append(text)
            print(f"  received: {text!r}", flush=True)
    def got(param):  # A and E both arrive as "kala_289" if Bale decodes %5F
        wanted = {f"/start {param}"} | ({"/start kala_289"} if "%5F" in param else set())
        return any(t in wanted for t in seen)

    passed = [label for label, param in VARIANTS.items() if got(param)]
    print(f"RESULT: /start messages received: {len(seen)}; with a parameter: "
          f"{sum(1 for t in seen if len(t.split()) > 1)}; variants that passed: {passed or 'none'}")


def main() -> None:
    if load_dotenv is not None:
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    token = os.environ.get("BALE_TEST_TOKEN", "").strip()
    if not token:  # a dev .env whose BALE_TOKEN is the test bot
        token = os.environ.get("BALE_TOKEN", "").strip()
        if token:
            print("BALE_TEST_TOKEN not set - using BALE_TOKEN; make sure it is a TEST bot.")
    if not token:
        sys.exit("Set BALE_TEST_TOKEN (a separate TEST bot) first.")
    with httpx.Client(timeout=40.0, trust_env=False) as client:
        me = call(client, token, "getMe")
        username = (me or {}).get("username", "?")
        pending = call(client, token, "getUpdates", {"timeout": 0}) or []
        offset = (pending[-1]["update_id"] + 1) if pending else None

        print(f"Bot: @{username}", flush=True)
        if "--formats" in sys.argv:
            formats(client, token, username, offset)
            return
        print(f"STEP 1: open this link in Bale and press Start:  https://ble.ir/{username}?start={PARAM}", flush=True)
        message, offset = wait_for(
            client, token, offset,
            lambda m: str(m.get("text") or "").startswith("/start"))
        if message is None:
            print("RESULT (a): no /start received within 15 minutes - nothing concluded.")
            return
        text = str(message.get("text") or "")
        if PARAM in text:
            print(f"RESULT (a): parameter PASSED - the bot received '/start {PARAM}'.")
        else:
            print(f"RESULT (a): parameter NOT passed - the bot received {text!r}.")

        chat_id = (message.get("chat") or {}).get("id")
        call(client, token, "sendMessage", {
            "chat_id": chat_id,
            "text": "آزمایش: لطفاً دکمهٔ «ارسال شماره» را بزنید.",
            "reply_markup": {
                "keyboard": [[{"text": "ارسال شماره", "request_contact": True}]],
                "resize_keyboard": True, "one_time_keyboard": True,
            },
        })
        print("STEP 2: in Bale, press the «ارسال شماره» button and share your number.", flush=True)
        message, offset = wait_for(client, token, offset, lambda m: bool(m.get("contact")))
        if message is None:
            print("RESULT (b): no contact received within 15 minutes - nothing concluded.")
            return
        contact = message.get("contact") or {}
        from_id = (message.get("from") or {}).get("id")
        print(f"contact fields: {sorted(contact)}")
        print(f"contact.user_id type: {type(contact.get('user_id')).__name__}; from.id type: {type(from_id).__name__}")
        if contact.get("user_id") is None:
            print("RESULT (b): contact.user_id MISSING.")
        elif str(contact.get("user_id")) == str(from_id):
            print("RESULT (b): contact.user_id PRESENT and equals from.id.")
        else:
            print("RESULT (b): contact.user_id PRESENT but differs from from.id.")
        call(client, token, "sendMessage", {
            "chat_id": chat_id, "text": "آزمایش تمام شد. سپاس.",
            "reply_markup": {"remove_keyboard": True},
        })


if __name__ == "__main__":
    main()
