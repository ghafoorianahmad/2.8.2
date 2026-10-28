"""The worker loop (REQUIREMENTS §5–6).

* price channel every ``TG_PRICE_INTERVAL_MIN`` (10): PDFs newer than the cursor
  go to ``/worker/pricelists`` (shopapi decides duplicate / older / held); the
  cursor moves past images and text posts too. First run: newest PDF only;
* proxy channels (default @ProxyMTProto) every ``TG_PROXY_COLLECT_HOURS`` (24),
  and hourly while fewer than ``TG_PROXY_POOL_SIZE`` (10) fast proxies work (v2.9.3:
  dead collected ones are retired by shopapi at once, so the pool refills): links read
  with the account, or from the public web preview (t.me/s/...) when not logged
  in / no proxy works; links the server never saw are tested with an anonymous
  client and only the working ones join the pool (v2.9.0);
* health check every ``TG_HEALTH_INTERVAL_SEC``: a failed ping switches to the
  next best proxy at once (pool ranking from shopapi, then ``TG_PROXY``);
* probe of the other proxies every ``TG_PROBE_INTERVAL_MIN`` with an anonymous
  client, so probation proxies collect history (the pool promotes/retires them);
* alerts (deduplicated by shopapi): login required, Telegram unreachable, a
  price-list PDF that cannot be downloaded (``telegram_pricelist_error``);
* a FloodWait from Telegram pauses every job for the time it asks (low rate).

Logs show proxy host:port and kind only, never secrets, keys or the session.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import secure_store
from .config import Settings
from .gateway import NotAuthorized, TelegramGateway, TgMessage
from tgproxy import ProxyLink, from_pool, parse_proxy_link
from .shopapi import ApiError, WorkerApi
from . import proxylinks, webpreview

log = logging.getLogger(__name__)

K_PRICE_LAST_ID = "tg_price_last_id"
K_COLLECTED_AT = "tg_proxy_collected_at"
K_PROXY_LAST_IDS = "tg_proxy_last_ids"
K_STATUS = "tg_status"
#: v2.9.1: version (id, edit time, size) of the newest list post that was sent
K_PRICE_VERSION = "tg_price_version"
#: v2.9.1: text posts after the list already sent ({channel:id: version})
K_PRICE_NOTES = "tg_price_notes"
#: v2.9.2: the last collection (shown on «سرور فروشگاه» also after a restart) and
#: «جمع‌آوری اکنون» from ShopAdmin (request time / the request already handled)
K_COLLECT_INFO = "tg_collect_info"
K_COLLECT_REQUEST = "tg_collect_request"
K_COLLECT_DONE = "tg_collect_done"
#: v2.13.0: «دریافت لیست اکنون» from ShopAdmin (request time / the request handled)
K_PRICE_REQUEST = "tg_price_request"
K_PRICE_DONE = "tg_price_done"

ROLE_PRICELIST = "pricelist"
ROLE_PROXY = "proxy"
#: v2.14.0: other price channels: every list is read and kept, never the basis by itself
ROLE_PRICE_OTHER = "price_other"
K_OTHER_LAST = "price_other:last_ids"
OTHER_FIRST_SCAN = 10
#: how long the channel roles are cached; the joined channels are listed this often
ROLES_TTL = 5 * 60
CHANNELS_INTERVAL_SEC = 6 * 3600
#: during sales hours (Tehran 07:00-21:00) the price channel is read at least this often
SALES_HOURS_MAX_INTERVAL = 20 * 60

#: Extra working proxies kept beyond TG_PROXY_POOL_SIZE (a failure must not empty it).
POOL_SPARE = 2
#: v2.9.3: slower than this (ms) does not count as healthy (shopapi ranks it last)
SLOW_MS = 5000
#: While fewer than pool_size proxies work, collect again after this long.
REFILL_AFTER = timedelta(hours=1)
#: How often the collection is considered (it decides itself whether it is due).
COLLECT_CHECK_SEC = 30 * 60
#: v2.9.2: right after a start a short pool is refilled at once, unless the last
#: collection is this recent (a restart loop must not hammer the channel)
START_REFILL_AFTER = timedelta(minutes=10)
#: v2.9.2: how often «جمع‌آوری اکنون» from ShopAdmin is looked for
REQUEST_CHECK_SEC = 20
#: v2.9.1: the newest posts of a proxy channel read at each collection
PROXY_SCAN = 100
#: Consecutive download failures of a price-list PDF before the owner is alerted.
PRICE_FAIL_ALERT = 3
ALERT_PRICELIST = "telegram_pricelist_error"
#: v2.13.0: a FloodWait longer than this tells the owner (once; shopapi deduplicates)
ALERT_FLOOD = "telegram_flood_wait"
FLOOD_ALERT_SEC = 3600
#: v2.13.0: while every job is paused the status is still published this often, so
#: «سرور فروشگاه» shows «paused until …» instead of a worker that looks dead
PAUSED_STATUS_SEC = 60
#: v2.13.0 watchdog: one round of jobs taking longer than this means something hangs;
#: the worker then exits and the supervisor starts it again (and tells the owner)
STEP_TIMEOUT_SEC = 30 * 60
#: v2.13.0: the heartbeat file is touched this often while the event loop runs
HEARTBEAT_SEC = 30


class WorkerStuck(RuntimeError):
    """One round of jobs did not finish within STEP_TIMEOUT_SEC."""


def flood_seconds(exc: BaseException) -> int:
    """Seconds Telegram asked us to wait (FloodWait and friends), else 0."""
    if type(exc).__name__ in ("FloodWaitError", "FloodPremiumWaitError", "SlowModeWaitError",
                              "FloodTestPhoneWaitError"):
        try:
            return max(1, int(getattr(exc, "seconds", 60) or 60))
        except (TypeError, ValueError):
            return 60
    return 0


#: Iran has no daylight saving time since 2022
TEHRAN = timezone(timedelta(hours=3, minutes=30), "Asia/Tehran")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _where(link: ProxyLink | None) -> str:
    return link.masked() if link else "direct connection"


class Worker:
    def __init__(self, settings: Settings, api: WorkerApi, gateway: TelegramGateway, *,
                 load_session: Callable[[], str] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = utcnow):
        self.s = settings
        self.api = api
        self.tg = gateway
        self._load_session = load_session or (lambda: secure_store.load_session(settings.session_file))
        self._clock = clock
        self._now = now
        self._down_since: float | None = None
        self._login_missing = False
        self._probe_offset = 0
        self._next = {"health": 0.0, "price": 0.0, "other_price": 0.0, "collect": 0.0, "probe": 0.0,
                      "channels": 0.0, "request": 0.0}
        #: v2.9.2: the first collection check after a start
        self._first_collect = True
        self._roles: list[dict] | None = None
        self._roles_at = 0.0
        self._paused_until = 0.0
        self._paused_status_at = 0.0
        self._price_failures = 0
        self.last_error = ""
        #: v2.9.0: shown on «سرور فروشگاه» (no secrets: refs, counts, times)
        self.price_info: dict = {}
        self.collect_info: dict = {}

    # ---- proxies / connection -----------------------------------------------------
    async def candidates(self) -> list[ProxyLink | None]:
        """Pool ranking (best first), the local TG_PROXY links, then direct
        (``None``) when TG_ALLOW_DIRECT is on."""
        links: list[ProxyLink | None] = []
        try:
            for item in await self.api.proxies():
                link = from_pool(item)
                if link is not None:
                    links.append(link)
        except ApiError as exc:
            log.warning("proxy pool unavailable: %s", exc)
        known = {(p.host, p.port, p.secret) for p in links}
        for raw in self.s.local_proxies:
            link = parse_proxy_link(raw)
            if link is not None and (link.host, link.port, link.secret) not in known:
                links.append(link)
        if self.s.allow_direct:
            links.append(None)
        return links

    async def _report(self, results: list[dict]) -> None:
        results = [r for r in results if r.get("id") is not None]
        if not results:
            return
        try:
            await self.api.report(results)
        except ApiError as exc:
            log.warning("proxy report failed: %s", exc)

    async def _alert(self, kind: str) -> None:
        try:
            await self.api.alert(kind)
        except ApiError as exc:
            log.warning("alert %s not delivered: %s", kind, exc)

    async def ensure_connected(self) -> bool:
        if self.tg.connected:
            return True
        try:
            session = self._load_session()
        except secure_store.SecureStoreError as exc:
            self.last_error = str(exc)
            if not self._login_missing:
                log.error("Telegram session unavailable: %s", exc)
            self._login_missing = True
            await self._alert("telegram_login_required")
            return False
        links = await self.candidates()
        results = []
        try:
            for link in links:
                try:
                    latency = await self.tg.connect(session, link)
                except NotAuthorized:
                    self.last_error = "the saved Telegram session is no longer logged in"
                    log.error("%s: run login.ps1 again", self.last_error)
                    self._login_missing = True
                    await self._alert("telegram_login_required")
                    return False
                except Exception as exc:  # noqa: BLE001 - any network failure = next proxy
                    log.info("connection via %s failed (%s)", _where(link), type(exc).__name__)
                    results.append({"id": link.id if link else None, "ok": False})
                    continue
                log.info("connected to Telegram via %s in %d ms", _where(link), latency)
                results.append({"id": link.id if link else None, "ok": True, "latency_ms": latency})
                self._down_since = None
                self._login_missing = False
                self.last_error = ""
                return True
        finally:
            await self._report(results)
        self.last_error = "no proxy could reach Telegram" if links else "no proxy configured"
        log.warning("%s (%d tried)", self.last_error, len(links))
        if self._down_since is None:
            self._down_since = self._clock()
        if self._clock() - self._down_since >= self.s.unreachable_alert_sec:
            await self._alert("telegram_unreachable")
        return False

    async def health_tick(self) -> None:
        if self.tg.connected:
            link = self.tg.proxy
            try:
                latency = await self.tg.ping()
                await self._report([{"id": link.id if link else None, "ok": True,
                                     "latency_ms": latency}])
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("health check via %s failed (%s); switching",
                            _where(link), type(exc).__name__)
                await self._report([{"id": link.id if link else None, "ok": False}])
                await self.tg.disconnect()
        await self.ensure_connected()

    async def probe_tick(self) -> None:
        """Test up to TG_PROBE_MAX other proxies (rotating through the pool)."""
        try:
            pool = [p for p in (from_pool(i) for i in await self.api.proxies()) if p]
        except ApiError as exc:
            log.warning("probe skipped: %s", exc)
            return
        current = self.tg.proxy.id if self.tg.proxy else None
        others = [p for p in pool if p.id != current]
        if not others:
            return
        start = self._probe_offset % len(others)
        batch = (others[start:] + others[:start])[: self.s.probe_max]
        self._probe_offset = start + len(batch)
        results = []
        for link in batch:
            try:
                latency = await self.tg.probe(link)
                results.append({"id": link.id, "ok": True, "latency_ms": latency})
            except Exception as exc:  # noqa: BLE001
                log.debug("probe %s failed (%s)", link.masked(), type(exc).__name__)
                results.append({"id": link.id, "ok": False})
        log.info("probed %d proxies: %d ok", len(results), sum(r["ok"] for r in results))
        await self._report(results)

    # ---- channels and roles (v2.9.1) -------------------------------------------------
    async def roles(self) -> list[dict]:
        """[{ref, role}] chosen in «تنظیمات سرور ← تلگرام» (cached a few minutes)."""
        now = self._clock()
        if self._roles is not None and now - self._roles_at < ROLES_TTL:
            return self._roles
        try:
            data = await self.api.channel_roles()
            items = data.get("channels") if isinstance(data, dict) else None
            self._roles = [{"ref": str(i.get("ref") or ""), "role": str(i.get("role") or ""),
                            "title": str(i.get("title") or "")}
                           for i in items or [] if isinstance(i, dict) and i.get("ref")]
            self._roles_at = now
        except ApiError as exc:
            log.debug("channel roles unavailable: %s", exc)
            if self._roles is None:
                return []
        return self._roles

    @staticmethod
    def _role_of(roles: list[dict], ref: str) -> str | None:
        for item in roles:
            if item["ref"].lower() == ref.lower():
                return item["role"]
        return None

    async def price_channel(self) -> str:
        """The channel with the «لیست قیمت» role, else TG_PRICE_CHANNEL (unless the
        admin gave that one another role)."""
        roles = await self.roles()
        chosen = [i["ref"] for i in roles if i["role"] == ROLE_PRICELIST]
        if chosen:
            return chosen[0]
        if self._role_of(roles, self.s.price_channel) in (None, "", ROLE_PRICELIST):
            return self.s.price_channel
        return ""

    async def proxy_channels(self) -> list[str]:
        """Channels with the «پراکسی» role, plus TG_PROXY_CHANNELS not given another role."""
        roles = await self.roles()
        out = [i["ref"] for i in roles if i["role"] == ROLE_PROXY]
        for channel in self.s.proxy_channels:
            if self._role_of(roles, channel) in (None, "", ROLE_PROXY) and \
                    channel.lower() not in {c.lower() for c in out}:
                out.append(channel)
        return out

    async def channels_tick(self) -> int:
        """Report the joined channels to shopapi (it alerts the admin about new ones)."""
        found = await self.tg.channels()
        await self.api.sync_channels([{"id": c.id, "username": c.username, "title": c.title,
                                       "broadcast": c.broadcast} for c in found])
        self._roles = None                 # a new channel may have a role now
        return len(found)

    # ---- price channel ------------------------------------------------------------
    async def price_tick(self, *, force: bool = False) -> int:
        """v2.9.1: read the newest posts of the price channel every time (not only
        those after a cursor): the newest list PDF that still exists is sent again
        when it changed (an edited post, a replaced file, or a deleted newest post),
        and the text posts after it (corrections, «فروش بسته») go to shopapi once
        per version. v2.13.0 ``force`` («دریافت لیست اکنون»): the newest list is sent
        even when it did not change (shopapi answers «duplicate», or reads a file
        it rejected before again). Returns how many lists were sent."""
        self.price_info["checked_at"] = self._now().isoformat(timespec="seconds")
        channel = await self.price_channel()
        self.price_info["channel"] = channel
        if not channel:
            return 0
        state = await self.api.get_state()
        messages = await self.tg.messages(channel, min_id=0, limit=self.s.first_run_scan)
        pdfs = [m for m in messages if m.is_pdf]
        sent = 0
        after = 0
        if pdfs:
            newest = max(pdfs, key=lambda m: m.id)
            after = newest.id
            version = f"{channel}:{newest.version}"
            if force or version != (state.get(K_PRICE_VERSION) or ""):
                if not await self._send_pdf(channel, newest):
                    return 0             # shopapi down: retry next time
                await self.api.put_state(K_PRICE_VERSION, version)
                sent = 1
            if newest.id > int(state.get(K_PRICE_LAST_ID) or 0):
                await self.api.put_state(K_PRICE_LAST_ID, str(newest.id))
        await self._send_notes(channel, [m for m in messages if not m.is_pdf and m.id > after
                                         and (m.text or "").strip()], state)
        return sent

    async def _send_notes(self, channel: str, notes: list[TgMessage], state: dict) -> None:
        try:
            done = json.loads(state.get(K_PRICE_NOTES) or "{}")
            if not isinstance(done, dict):
                done = {}
        except ValueError:
            done = {}
        changed = False
        for msg in notes:
            key = f"{channel}:{msg.id}"
            if done.get(key) == msg.version:
                continue
            ref = f"t.me/{channel}/{msg.id}"
            posted = msg.published.isoformat() if msg.published else None
            try:
                result = await self.api.post_note(msg.text, source_ref=ref, posted_at=posted)
            except ApiError as exc:
                log.warning("price channel post %s not delivered: %s", ref, exc)
                break
            log.info("price channel post %s -> %s", ref, (result or {}).get("kind"))
            done[key] = msg.version
            changed = True
        if changed:
            keep = {f"{channel}:{m.id}" for m in notes}
            done = {k: v for k, v in done.items() if k in keep or not k.startswith(channel + ":")}
            await self.api.put_json_state(K_PRICE_NOTES, dict(list(done.items())[-60:]))

    async def _send_pdf(self, channel: str, msg: TgMessage) -> bool:
        ref = f"t.me/{channel}/{msg.id}"
        if msg.file_size > self.s.pdf_max_bytes:
            log.warning("skipped %s: %d bytes is over the limit", ref, msg.file_size)
            self._price_result(ref, "too_large")
            await self._alert(ALERT_PRICELIST)
            return True
        try:
            data = await self.tg.download(msg, self.s.pdf_max_bytes)
        except ValueError:
            log.warning("skipped %s: unexpected download result", ref)
            self._price_result(ref, "download_failed")
            await self._alert(ALERT_PRICELIST)
            return True
        except Exception:
            self._price_failures += 1
            self._price_result(ref, "download_failed")
            if self._price_failures >= PRICE_FAIL_ALERT:
                await self._alert(ALERT_PRICELIST)
            raise                       # a network problem: check the connection now
        self._price_failures = 0
        if not data.startswith(b"%PDF"):
            log.warning("skipped %s: not a PDF file", ref)
            self._price_result(ref, "not_pdf")
            await self._alert(ALERT_PRICELIST)
            return True
        posted = msg.published.isoformat() if msg.published else None
        try:
            result = await self.api.post_pricelist(data, source_ref=ref, posted_at=posted,
                                                   latest=True)
        except ApiError as exc:
            log.warning("price list %s not delivered: %s", ref, exc)
            return False
        log.info("price list %s -> %s %s", ref, result.get("outcome"),
                 "; ".join(result.get("reasons") or []))
        self._price_result(ref, str(result.get("outcome") or ""))
        return True

    async def other_price_tick(self) -> int:
        """v2.14.0: the new posts of the other price channels (files and price text)
        go to shopapi once each; the first time only the newest few. Returns how many."""
        chans = [i for i in await self.roles() if i["role"] == ROLE_PRICE_OTHER and i["ref"]]
        if not chans:
            return 0
        state = await self.api.get_state()
        try:
            last = json.loads(state.get(K_OTHER_LAST) or "{}")
        except ValueError:
            last = {}
        sent = 0
        for item in chans:
            ref, title = item["ref"], item.get("title") or item["ref"]
            start = int(last.get(ref) or 0)
            messages = await self.tg.messages(ref, min_id=start,
                                              limit=OTHER_FIRST_SCAN if not start else 50)
            for msg in sorted(messages, key=lambda m: m.id):
                data, text = b"", ""
                if msg.media_kind and msg.file_size <= self.s.pdf_max_bytes:
                    data = await self.tg.download(msg, self.s.pdf_max_bytes)
                elif not msg.media_kind and any(ch.isdigit() for ch in (msg.text or "")):
                    text = msg.text
                if data or text:
                    posted = msg.published.isoformat() if msg.published else None
                    await self.api.post_channel_file(
                        channel=ref, title=title, data=data, text=text, file_name=msg.file_name,
                        source_ref=f"t.me/{ref}/{msg.id}", posted_at=posted)
                    sent += 1
                last[ref] = max(int(last.get(ref) or 0), msg.id)
        await self.api.put_json_state(K_OTHER_LAST, last)
        return sent

    def _price_result(self, ref: str, outcome: str) -> None:
        self.price_info.update(ref=ref, outcome=outcome,
                               at=self._now().isoformat(timespec="seconds"))

    # ---- proxy channels -------------------------------------------------------------
    def collect_due(self, collected_at: str, healthy: int | None = None, *,
                    first: bool = False) -> bool:
        """Daily (TG_PROXY_COLLECT_HOURS), or hourly while the pool is short.
        v2.9.2: right after a start (``first``) a short pool does not wait for the
        hour of the previous run (2.9.1 waited up to an hour after an upgrade)."""
        try:
            last = datetime.fromisoformat(collected_at)
        except ValueError:
            return True
        elapsed = self._now() - last
        if elapsed >= timedelta(hours=self.s.proxy_collect_hours):
            return True
        short = healthy is not None and healthy < self.s.pool_size
        return short and elapsed >= (START_REFILL_AFTER if first else REFILL_AFTER)

    async def healthy_count(self) -> int:
        """Usable proxies that worked at their last check. v2.9.3: a slow one
        (over SLOW_MS) does not count, so faster ones are looked for."""
        try:
            pool = await self.api.proxies()
        except ApiError:
            return 0
        return sum(1 for p in pool if p.get("last_ok_at") and not p.get("failing_now")
                   and int(p.get("last_latency_ms") or 0) <= SLOW_MS)

    async def _channel_links(self, channel: str, last_ids: dict,
                             errors: list[str] | None = None) -> tuple[list[str], str]:
        """Proxy links of one channel, newest first: with the account when it is
        connected, else (or when that fails / finds none) from the public web preview.
        v2.9.1: always the newest PROXY_SCAN posts (links the server already knows
        are not tested again), from the text, the link entities and the buttons, in
        every format (``proxylinks``)."""
        errors = errors if errors is not None else []
        if self.tg.connected:
            try:
                messages = await self.tg.messages(channel, min_id=0, limit=PROXY_SCAN)
            except Exception as exc:  # noqa: BLE001 - one bad channel must not stop the rest
                if flood_seconds(exc):
                    raise
                log.warning("proxy channel %s unreadable (%s)", channel, type(exc).__name__)
                errors.append(f"{channel}: {type(exc).__name__}")
            else:
                if messages:
                    last_ids[channel] = max(m.id for m in messages)
                newest = list(reversed(messages))
                links = proxylinks.extract_all([t for m in newest for t in [m.text, *m.urls]])
                if links:
                    return links, "account"
                log.info("proxy channel %s: %d posts read, no proxy link in them", channel,
                         len(messages))
                errors.append(f"{channel}: {len(messages)} posts, no links")
        if self.s.web_preview:
            try:
                return await webpreview.fetch_links(channel), "web"
            except webpreview.PreviewError as exc:
                log.info("web preview of %s: %s", channel, exc)
                errors.append(f"{channel} web: {exc}")
        return [], ""

    async def collect_tick(self, *, force: bool = False) -> int:
        """New proxy links -> tested -> the working ones into the pool. Returns how
        many working proxies were added."""
        channels = await self.proxy_channels()
        state = await self.api.get_state()
        first, self._first_collect = self._first_collect, False
        if not self.collect_info:
            self.collect_info = self._stored_collect_info(state)
        if not channels:
            if force:
                self.collect_info = {"at": self._now().isoformat(timespec="seconds"),
                                     "found": 0, "tested": 0, "added": 0, "via": "",
                                     "error": "no proxy channel (TG_PROXY_CHANNELS / roles)"}
                await self.api.put_json_state(K_COLLECT_INFO, self.collect_info)
            return 0
        healthy = await self.healthy_count()
        if not force and not self.collect_due(state.get(K_COLLECTED_AT) or "", healthy,
                                              first=first):
            return 0
        try:
            last_ids = json.loads(state.get(K_PROXY_LAST_IDS) or "{}")
            if not isinstance(last_ids, dict):
                last_ids = {}
        except ValueError:
            last_ids = {}
        found: list[tuple[str, str]] = []
        ways: list[str] = []
        errors: list[str] = []
        for channel in channels:
            links, way = await self._channel_links(channel, last_ids, errors)
            if way:
                ways.append(way)
            seen = {raw for raw, _ in found}
            found += [(raw, f"channel:{channel}") for raw in links if raw not in seen]
            log.info("proxy channel %s: %d links (%s)", channel, len(links), way or "unreadable")
        added, tested = await self._test_and_add(found, healthy)
        await self.api.put_json_state(K_PROXY_LAST_IDS, last_ids)
        await self.api.put_state(K_COLLECTED_AT, self._now().isoformat(timespec="seconds"))
        self.collect_info = {"at": self._now().isoformat(timespec="seconds"), "found": len(found),
                             "tested": tested, "added": added, "via": ",".join(ways),
                             "error": "; ".join(errors)[:300] if not found else ""}
        await self.api.put_json_state(K_COLLECT_INFO, self.collect_info)
        if added and not self.tg.connected:
            self._next["health"] = 0.0          # a new proxy may get us connected now
        return added

    @staticmethod
    def _stored_collect_info(state: dict) -> dict:
        try:
            value = json.loads(state.get(K_COLLECT_INFO) or "{}")
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    async def request_tick(self) -> bool:
        """v2.9.2 «جمع‌آوری اکنون» / v2.13.0 «دریافت لیست اکنون» in ShopAdmin: each
        request once. The price list needs the account: without a connection the
        request waits (it is not marked handled) until the reader is connected."""
        state = await self.api.get_state()
        handled = False
        price_wanted = state.get(K_PRICE_REQUEST) or ""
        if price_wanted and price_wanted != (state.get(K_PRICE_DONE) or "") \
                and self.tg.connected:
            await self.api.put_state(K_PRICE_DONE, price_wanted)
            log.info("price list requested from ShopAdmin")
            self._next["price"] = self._clock() + self.price_interval()
            await self.price_tick(force=True)
            handled = True
        wanted = state.get(K_COLLECT_REQUEST) or ""
        if wanted and wanted != (state.get(K_COLLECT_DONE) or ""):
            await self.api.put_state(K_COLLECT_DONE, wanted)
            log.info("proxy collection requested from ShopAdmin")
            await self.collect_tick(force=True)
            handled = True
        return handled

    async def _test_and_add(self, found: list[tuple[str, str]], healthy: int) -> tuple[int, int]:
        """Test links the server never saw, until the pool holds pool_size + spare
        working proxies (at most TG_PROXY_TEST_MAX tests). Returns (added, tested)."""
        need = self.s.pool_size + POOL_SPARE - healthy
        if not found or need <= 0:
            return 0, 0
        unknown: set[str] = set()
        raws = [raw for raw, _ in found]
        for start in range(0, len(raws), 500):
            unknown.update(await self.api.unknown(raws[start:start + 500]))
        by_source: dict[str, tuple[list[dict], list[str]]] = {}
        added = tested = 0
        for raw, source in found:
            if raw not in unknown:
                continue
            if added >= need or tested >= self.s.proxy_test_max:
                break
            link = parse_proxy_link(raw)
            if link is None:
                continue
            tested += 1
            ok, bad = by_source.setdefault(source, ([], []))
            try:
                latency = await self.tg.probe(link)
            except Exception as exc:  # noqa: BLE001 - a dead proxy is the common case
                log.debug("test %s failed (%s)", link.masked(), type(exc).__name__)
                bad.append(raw)
                continue
            ok.append({"link": raw, "latency_ms": latency})
            added += 1
        for source, (ok, bad) in by_source.items():
            if ok or bad:
                await self.api.candidates([], source, tested=ok, failed=bad)
        log.info("tested %d new proxies: %d working", tested, added)
        return added, tested

    # ---- status / loop ----------------------------------------------------------------
    async def publish_status(self) -> None:
        link = self.tg.proxy
        paused = max(0.0, self._paused_until - self._clock())
        status = {
            "connected": self.tg.connected,
            "proxy": _where(link) if self.tg.connected else "",
            "proxy_id": link.id if link else None,
            "login_required": self._login_missing,
            "error": self.last_error[:200],
            "at": self._now().isoformat(timespec="seconds"),
            # v2.13.0: every job waits for Telegram until this time (FloodWait)
            "paused_until": (self._now() + timedelta(seconds=paused)).isoformat(
                timespec="seconds") if paused else None,
            # v2.9.0 (no secrets: which key kind, the channel, counts and times)
            "api_preset": self.s.api_preset,
            "price_channel": self.price_info.get("channel") or self.s.price_channel,
            "pool_size": self.s.pool_size,
            "price": dict(self.price_info),
            "collect": dict(self.collect_info),
        }
        try:
            await self.api.put_json_state(K_STATUS, status)
        except ApiError as exc:
            log.debug("status not published: %s", exc)

    async def step(self) -> None:
        """Run whatever is due (called every few seconds)."""
        now = self._clock()
        if now < self._paused_until:
            # v2.13.0: still say so (before, a long wait looked like a dead worker)
            if now - self._paused_status_at >= PAUSED_STATUS_SEC:
                self._paused_status_at = now
                await self.publish_status()
            return
        if now >= self._next["health"]:
            self._next["health"] = now + self.s.health_interval_sec
            try:
                await self.health_tick()
            except Exception as exc:  # noqa: BLE001
                if not self._flood(exc, now):
                    raise
            await self.publish_status()
        connected = self.tg.connected
        if not connected:
            # Retry sooner than the health interval while down, but not in a tight loop.
            self._next["health"] = min(self._next["health"], now + 60)
        for name, interval, job, needs_connection in (
            ("channels", CHANNELS_INTERVAL_SEC, self.channels_tick, True),
            ("price", self.price_interval(), self.price_tick, True),
            ("other_price", self.price_interval(), self.other_price_tick, True),
            # v2.9.0: also without a connection (web preview + anonymous tests)
            ("collect", COLLECT_CHECK_SEC, self.collect_tick, False),
            ("probe", self.s.probe_interval_sec, self.probe_tick, True),
            ("request", REQUEST_CHECK_SEC, self.request_tick, False),
        ):
            if now < self._next[name] or (needs_connection and not connected):
                continue
            self._next[name] = now + interval
            result = None
            try:
                result = await job()
            except ApiError as exc:
                log.warning("%s: %s", name, exc)
            except Exception as exc:  # noqa: BLE001 - FloodWait, network, ...
                if self._flood(exc, now):
                    await self.publish_status()
                    break
                log.warning("%s failed (%s)", name, type(exc).__name__)
                if name != "probe":
                    self._next["health"] = 0.0      # check the connection now
            if name in ("price", "collect") or (name == "request" and result):
                await self.publish_status()

    def price_interval(self) -> int:
        """TG_PRICE_INTERVAL_MIN, at most every 20 minutes during sales hours."""
        local = self._now().astimezone(TEHRAN)
        if 7 <= local.hour < 21:
            return min(self.s.price_interval_sec, SALES_HOURS_MAX_INTERVAL)
        return self.s.price_interval_sec

    def _flood(self, exc: BaseException, now: float) -> bool:
        """A FloodWait: pause every job for as long as Telegram asks."""
        seconds = flood_seconds(exc)
        if not seconds:
            return False
        self._paused_until = now + seconds + 5
        self._paused_status_at = 0.0
        self.last_error = f"Telegram asked to wait {seconds} s"
        log.warning("Telegram asked to wait %d s: every job paused", seconds)
        if seconds >= FLOOD_ALERT_SEC:
            self._flood_alert = True
        return True

    _flood_alert = False

    async def run(self, stop: asyncio.Event, *, heartbeat: Callable[[], None] | None = None,
                  step_timeout: float = STEP_TIMEOUT_SEC) -> None:
        """v2.13.0: ``heartbeat`` is called every HEARTBEAT_SEC by its own task (the
        supervisor restarts a worker whose event loop stops); one round of jobs
        longer than ``step_timeout`` raises WorkerStuck (the process exits and the
        supervisor starts it again)."""
        log.info("shoptg worker started (price channel @%s, %d proxy channels)",
                 self.s.price_channel, len(self.s.proxy_channels))
        beat = asyncio.create_task(self._beat(heartbeat, stop)) if heartbeat else None
        try:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(self.step(), step_timeout)
                except asyncio.TimeoutError:
                    log.error("one round of jobs took over %d s: restarting the reader",
                              int(step_timeout))
                    raise WorkerStuck() from None
                if self._flood_alert:
                    self._flood_alert = False
                    await self._alert(ALERT_FLOOD)
                try:
                    await asyncio.wait_for(stop.wait(), 5)
                except asyncio.TimeoutError:
                    pass
        finally:
            if beat is not None:
                beat.cancel()
            await self.tg.disconnect()
            log.info("shoptg worker stopped")

    @staticmethod
    async def _beat(heartbeat: Callable[[], None], stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                heartbeat()
            except Exception:  # noqa: BLE001 - a missing heartbeat only means a restart
                log.debug("heartbeat not written", exc_info=True)
            await asyncio.sleep(HEARTBEAT_SEC)
