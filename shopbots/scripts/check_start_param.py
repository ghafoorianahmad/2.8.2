"""Does Bale pass the /start parameter of a deep link to the bot? (REQUIREMENTS §7)

Use ONLY a separate Bale TEST bot - never the shop's real bot while ShopServer
is polling it (two pollers steal each other's updates).

    $env:BALE_TEST_TOKEN = Read-Host -AsSecureString ...   # or set it any other way
    .\\.venv\\Scripts\\python.exe scripts\\check_start_param.py

The script prints the deep link, waits (up to 3 minutes) for you to open it in
Bale and press «شروع», then reports what text the bot received. The token is
read from the environment only and is never printed or logged.
"""
from __future__ import annotations

import os
import sys
import time

import httpx

API_BASE = os.environ.get("BALE_API_BASE", "https://tapi.bale.ai").rstrip("/")
PARAM = "kala_289"
WAIT_SECONDS = 180


def call(client: httpx.Client, token: str, method: str, payload: dict | None = None):
    try:
        response = client.post(f"{API_BASE}/bot{token}/{method}", json=payload or {})
    except httpx.HTTPError as exc:  # never show the URL: it contains the token
        sys.exit(f"{method}: network error ({type(exc).__name__})")
    data = response.json() if response.content else {}
    if not data.get("ok"):
        sys.exit(f"{method}: HTTP {response.status_code} {data.get('description', '')}")
    return data.get("result")


def main() -> None:
    token = os.environ.get("BALE_TEST_TOKEN", "").strip()
    if not token:
        sys.exit("Set BALE_TEST_TOKEN (a separate TEST bot) first.")
    with httpx.Client(timeout=40.0, trust_env=False) as client:
        me = call(client, token, "getMe")
        username = (me or {}).get("username", "?")
        # skip anything already queued
        pending = call(client, token, "getUpdates", {"timeout": 0}) or []
        offset = (pending[-1]["update_id"] + 1) if pending else None

        print(f"Bot: @{username}")
        print(f"Open this link in Bale and press Start:  https://ble.ir/{username}?start={PARAM}")
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            payload = {"timeout": 25, "allowed_updates": ["message"]}
            if offset is not None:
                payload["offset"] = offset
            for update in call(client, token, "getUpdates", payload) or []:
                offset = update["update_id"] + 1
                text = str((update.get("message") or {}).get("text") or "")
                if not text.startswith("/start"):
                    continue
                if PARAM in text:
                    print(f"RESULT: parameter PASSED - the bot received '/start {PARAM}'.")
                else:
                    print(f"RESULT: parameter NOT passed - the bot received {text!r}.")
                # acknowledge what we read
                call(client, token, "getUpdates", {"offset": offset, "timeout": 0})
                return
        print("RESULT: no /start received within 3 minutes - nothing concluded.")


if __name__ == "__main__":
    main()
