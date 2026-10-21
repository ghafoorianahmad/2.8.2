"""Telegram login of the shop's reader account from ShopAdmin (v2.9.0).

«تنظیمات سرور» (ShopAdmin on the shop server, run as administrator) starts
``ShopSystem.exe --tg-login`` and talks to it in JSON lines over stdin/stdout:

    -> {"cmd": "start", "phone": "+98...", "proxy": "<optional tg://proxy link>"}
    <- {"event": "connected", "via": "host:443 (ee)"}  then  {"event": "code_sent"}
    -> {"cmd": "code", "code": "12345"}
    <- {"event": "password_needed"}                     (two-step verification)
    -> {"cmd": "password", "password": "..."}
    <- {"event": "done"}                                (session saved, encrypted)
    <- {"event": "error", "code": "code_invalid", "retry": true, ...}
    -> {"cmd": "cancel"}

The phone, code and password live only in memory and are never logged or
echoed back; the session goes straight into the DPAPI-encrypted file with the
SYSTEM / Administrators (+ service account read) ACL (``secure_store``).
The connection tries the proxy typed in the form, ``TG_PROXY``, the server's
proxy pool, then a direct connection.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Callable

from tgproxy import ProxyLink, from_pool, parse_proxy_link

from . import secure_store
from .config import Settings
from .gateway import TelegramGateway

log = logging.getLogger(__name__)

MAX_TRIES = 3


def _error(code: str, *, retry: bool = False, **extra: Any) -> dict:
    return {"event": "error", "code": code, "retry": retry, **extra}


def _where(link: ProxyLink | None) -> str:
    return link.masked() if link else "direct"


class LoginFlow:
    def __init__(self, settings: Settings, *, gateway: TelegramGateway | None = None,
                 pool: Callable[[], Any] | None = None,
                 save: Callable[..., None] = secure_store.save_session) -> None:
        self.s = settings
        self.tg = gateway or TelegramGateway(settings.api_id, settings.api_hash,
                                             timeout=settings.connect_timeout_sec,
                                             device=settings.device())
        self._pool = pool
        self._save = save
        self.client: Any = None
        self._phone = ""
        self._hash = ""
        self._code_tries = 0
        self._password_tries = 0
        self.state = "idle"        # idle -> code -> password -> done

    def use_key(self, preset: str, api_id: str = "", api_hash: str = "") -> bool:
        """The key chosen in the form (not saved yet): tdesktop / custom; empty
        custom values keep the saved ones. False when the custom key is missing."""
        from dataclasses import replace

        from .config import TDESKTOP_API_HASH, TDESKTOP_API_ID

        if preset == "tdesktop":
            self.s = replace(self.s, api_preset="tdesktop", api_id=TDESKTOP_API_ID,
                             api_hash=TDESKTOP_API_HASH)
        elif preset == "custom":
            new_id = int(api_id) if str(api_id).isdigit() else (
                self.s.api_id if self.s.api_preset == "custom" else 0)
            new_hash = api_hash or (self.s.api_hash if self.s.api_preset == "custom" else "")
            self.s = replace(self.s, api_preset="custom", api_id=new_id, api_hash=new_hash)
        else:
            return True
        if not self.s.api_id or not self.s.api_hash:
            return False
        self.tg = TelegramGateway(self.s.api_id, self.s.api_hash,
                                  timeout=self.s.connect_timeout_sec, device=self.s.device(),
                                  client_factory=self.tg._factory)
        return True

    # ---- connection ------------------------------------------------------------
    async def proxies(self, typed: str) -> list[ProxyLink | None]:
        links: list[ProxyLink | None] = []
        first = parse_proxy_link(typed) if typed else None
        if first is not None:
            links.append(first)
        for raw in self.s.local_proxies:
            link = parse_proxy_link(raw)
            if link is not None:
                links.append(link)
        if self._pool is not None:
            try:
                for item in await self._pool():
                    link = from_pool(item)
                    if link is not None:
                        links.append(link)
            except Exception as exc:  # noqa: BLE001 - the pool is optional here
                log.info("proxy pool unavailable for the login (%s)", type(exc).__name__)
        seen: set = set()
        unique: list[ProxyLink | None] = []
        for link in links:
            key = (link.host, link.port, link.secret)
            if key not in seen:
                seen.add(key)
                unique.append(link)
        if self.s.allow_direct:
            unique.append(None)
        return unique

    async def _connect(self, typed: str) -> ProxyLink | None | bool:
        timeout = self.s.connect_timeout_sec
        for link in await self.proxies(typed):
            client = self.tg.make_client("", link)
            try:
                await asyncio.wait_for(client.connect(), timeout)
            except Exception as exc:  # noqa: BLE001 - next proxy
                log.info("login connection via %s failed (%s)", _where(link), type(exc).__name__)
                await _quiet(client)
                continue
            self.client = client
            return link
        return False

    # ---- steps -------------------------------------------------------------------------
    async def start(self, phone: str, proxy: str = "") -> list[dict]:
        phone = "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+")
        if len(phone.lstrip("+")) < 8:
            return [_error("phone_invalid", retry=True)]
        if self.s.missing() and set(self.s.missing()) - {"WORKER_API_KEY"}:
            return [_error("api_missing")]
        await self.close()
        link = await self._connect(proxy)
        if link is False:
            return [_error("no_connection", retry=True)]
        out = [{"event": "connected", "via": _where(link)}]
        from telethon import errors

        try:
            sent = await self.client.send_code_request(phone)
        except errors.PhoneNumberInvalidError:
            return out + [_error("phone_invalid", retry=True)]
        except errors.PhoneNumberBannedError:
            return out + [_error("phone_banned")]
        except errors.ApiIdInvalidError:
            return out + [_error("api_invalid")]
        except errors.FloodWaitError as exc:
            return out + [_error("flood", seconds=int(getattr(exc, "seconds", 0) or 0))]
        except Exception as exc:  # noqa: BLE001
            log.warning("send_code_request failed (%s)", type(exc).__name__)
            return out + [_error("unexpected", retry=True, kind=type(exc).__name__)]
        self._phone, self._hash = phone, sent.phone_code_hash
        self._code_tries = self._password_tries = 0
        self.state = "code"
        return out + [{"event": "code_sent"}]

    async def code(self, code: str) -> list[dict]:
        if self.state != "code" or self.client is None:
            return [_error("bad_state")]
        code = "".join(ch for ch in (code or "") if ch.isdigit())
        from telethon import errors

        try:
            await self.client.sign_in(phone=self._phone, code=code, phone_code_hash=self._hash)
        except errors.SessionPasswordNeededError:
            self.state = "password"
            return [{"event": "password_needed"}]
        except errors.PhoneCodeInvalidError:
            self._code_tries += 1
            return [_error("code_invalid", retry=self._code_tries < MAX_TRIES,
                           left=MAX_TRIES - self._code_tries)]
        except errors.PhoneCodeExpiredError:
            return [_error("code_expired")]
        except errors.PhoneNumberUnoccupiedError:
            return [_error("not_registered")]
        except errors.FloodWaitError as exc:
            return [_error("flood", seconds=int(getattr(exc, "seconds", 0) or 0))]
        except Exception as exc:  # noqa: BLE001
            log.warning("sign_in failed (%s)", type(exc).__name__)
            return [_error("unexpected", retry=True, kind=type(exc).__name__)]
        return await self._finish()

    async def password(self, password: str) -> list[dict]:
        if self.state != "password" or self.client is None:
            return [_error("bad_state")]
        from telethon import errors

        try:
            await self.client.sign_in(password=password or "")
        except errors.PasswordHashInvalidError:
            self._password_tries += 1
            return [_error("password_invalid", retry=self._password_tries < MAX_TRIES,
                           left=MAX_TRIES - self._password_tries)]
        except errors.FloodWaitError as exc:
            return [_error("flood", seconds=int(getattr(exc, "seconds", 0) or 0))]
        except Exception as exc:  # noqa: BLE001
            log.warning("password sign_in failed (%s)", type(exc).__name__)
            return [_error("unexpected", retry=True, kind=type(exc).__name__)]
        finally:
            password = ""  # noqa: F841 - drop the reference early
        return await self._finish()

    async def _finish(self) -> list[dict]:
        try:
            authorized = await self.client.is_user_authorized()
        except Exception:  # noqa: BLE001
            authorized = False
        if not authorized:
            return [_error("not_authorized", retry=True)]
        session = self.client.session.save()
        try:
            self._save(self.s.session_file, session, self.s.service_account)
        except secure_store.SecureStoreError as exc:
            log.error("session not saved: %s", exc)
            return [_error("save_failed")]
        finally:
            session = ""  # noqa: F841
        self.state = "done"
        self._phone = self._hash = ""
        log.info("Telegram login complete; session saved (encrypted)")
        return [{"event": "done"}]

    async def close(self) -> None:
        client, self.client = self.client, None
        if client is not None:
            await _quiet(client)


async def _quiet(client) -> None:
    try:
        await asyncio.wait_for(client.disconnect(), 10)
    except Exception:  # noqa: BLE001
        pass


def _stdin_line() -> str:
    return sys.stdin.readline()


def _stdout_write(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


async def run_pipe(settings: Settings, *, read: Callable[[], str] = _stdin_line,
                   write: Callable[[dict], None] = _stdout_write,
                   flow: LoginFlow | None = None) -> int:
    """The JSON-lines loop; exits on ``cancel``, end of input or after ``done``."""
    api = None
    if flow is None:
        pool = None
        if settings.worker_api_key:
            from .shopapi import WorkerApi

            api = WorkerApi(settings)
            pool = api.proxies
        flow = LoginFlow(settings, pool=pool)
    loop = asyncio.get_running_loop()
    write({"event": "ready", "preset": settings.api_preset,
           "has_session": settings.session_file.exists()})
    try:
        while True:
            line = await loop.run_in_executor(None, read)
            if not line:
                return 1
            try:
                msg = json.loads(line)
            except ValueError:
                write(_error("bad_request"))
                continue
            cmd = str(msg.get("cmd") or "") if isinstance(msg, dict) else ""
            if cmd == "cancel":
                return 1
            if cmd == "start":
                if msg.get("preset") and not flow.use_key(str(msg.get("preset")),
                                                          str(msg.get("api_id") or ""),
                                                          str(msg.get("api_hash") or "")):
                    events = [_error("api_missing")]
                else:
                    events = await flow.start(str(msg.get("phone") or ""),
                                              str(msg.get("proxy") or ""))
            elif cmd == "code":
                events = await flow.code(str(msg.get("code") or ""))
            elif cmd == "password":
                events = await flow.password(str(msg.get("password") or ""))
            else:
                events = [_error("bad_request")]
            msg = {}
            for event in events:
                write(event)
            if flow.state == "done":
                return 0
    finally:
        await flow.close()
        if api is not None:
            await api.aclose()
