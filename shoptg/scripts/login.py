"""One-time Telegram login of the shop's account (run ON the shop server).

    .\\login.ps1            (elevated PowerShell, from the shoptg folder)

Every answer (phone, login code, 2FA password, proxy link) is typed into a
hidden prompt and kept only in memory. The resulting session is saved
DPAPI-encrypted (LocalMachine) with an ACL for SYSTEM + Administrators (+ the
read-only service account in TG_SERVICE_ACCOUNT). Nothing secret is printed.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import secure_store  # noqa: E402
from app.config import Settings  # noqa: E402
from app.gateway import TelegramGateway  # noqa: E402
from app.interactive import choose_proxies, hidden, require_admin, require_api_credentials  # noqa: E402

MAX_CODE_TRIES = 3


async def connect_any(gateway: TelegramGateway, links, timeout: float):
    for link in links:
        client = gateway.make_client("", link)
        try:
            await asyncio.wait_for(client.connect(), timeout)
            print("Connected to Telegram", "via " + link.masked() if link else "directly")
            return client
        except Exception as exc:  # noqa: BLE001
            print(f"Could not connect {'via ' + link.masked() if link else 'directly'}: "
                  f"{type(exc).__name__}")
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
    return None


async def login(settings: Settings) -> int:
    from telethon.errors import (
        PasswordHashInvalidError,
        PhoneCodeExpiredError,
        PhoneCodeInvalidError,
        PhoneNumberInvalidError,
        SessionPasswordNeededError,
    )

    gateway = TelegramGateway(settings.api_id, settings.api_hash, device=settings.device(),
                              timeout=settings.connect_timeout_sec)
    client = await connect_any(gateway, choose_proxies(settings), settings.connect_timeout_sec)
    if client is None:
        print("No connection to Telegram. Check the proxy link and try again.")
        return 1
    try:
        phone = hidden("Phone number of the shop's Telegram account (hidden, e.g. +98912...): ")
        try:
            sent = await client.send_code_request(phone)
        except PhoneNumberInvalidError:
            print("Telegram says this phone number is invalid.")
            return 1
        print("Telegram sent a login code (usually inside the Telegram app of that account).")
        for attempt in range(1, MAX_CODE_TRIES + 1):
            code = hidden("Login code (hidden): ").replace(" ", "").replace("-", "")
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
                break
            except SessionPasswordNeededError:
                for _ in range(MAX_CODE_TRIES):
                    password = hidden("Two-step verification password (hidden): ")
                    try:
                        await client.sign_in(password=password)
                        break
                    except PasswordHashInvalidError:
                        print("Wrong password.")
                    finally:
                        password = ""
                else:
                    return 1
                break
            except PhoneCodeInvalidError:
                print(f"Wrong code ({attempt}/{MAX_CODE_TRIES}).")
            except PhoneCodeExpiredError:
                print("The code expired. Run the script again.")
                return 1
        else:
            return 1
        if not await client.is_user_authorized():
            print("Login did not complete.")
            return 1
        session = client.session.save()
        secure_store.save_session(settings.session_file, session, settings.service_account)
        session = ""
        print("Login OK. The session is saved encrypted (DPAPI LocalMachine, Administrators/SYSTEM only):")
        print("  ", settings.session_file)
        return 0
    finally:
        phone = code = ""  # noqa: F841 - drop references early
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    require_admin()
    settings = Settings.from_env()
    require_api_credentials(settings)
    if settings.session_file.exists():
        answer = input("A session already exists. Replace it with a new login? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Kept the existing session.")
            return 0
    return asyncio.run(login(settings))


if __name__ == "__main__":
    sys.exit(main())
