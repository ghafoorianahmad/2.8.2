"""The worker loop (REQUIREMENTS §5–6).

* price channel every ``TG_PRICE_INTERVAL_MIN`` (10): PDFs newer than the cursor
  go to ``/worker/pricelists`` (shopapi decides duplicate / older / held); the
  cursor moves past images and text posts too. First run: newest PDF only;
* proxy channels every ``TG_PROXY_COLLECT_DAYS`` (7): links -> candidates;
* health check every ``TG_HEALTH_INTERVAL_SEC``: a failed ping switches to the
  next best proxy at once (pool ranking from shopapi, then ``TG_PROXY``);
* probe of the other proxies every ``TG_PROBE_INTERVAL_MIN`` with an anonymous
  client, so probation proxies collect history (the pool promotes/retires them);
* alerts (deduplicated by shopapi): login required, Telegram unreachable.

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
from tgproxy import ProxyLink, extract_links, from_pool, parse_proxy_link
from .shopapi import ApiError, WorkerApi

log = logging.getLogger(__name__)

K_PRICE_LAST_ID = "tg_price_last_id"
K_COLLECTED_AT = "tg_proxy_collected_at"
K_PROXY_LAST_IDS = "tg_proxy_last_ids"
K_STATUS = "tg_status"


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
        self._next = {"health": 0.0, "price": 0.0, "collect": 0.0, "probe": 0.0}
        self.last_error = ""

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

    # ---- price channel ------------------------------------------------------------
    async def price_tick(self) -> int:
        """Send new PDFs to shopapi; returns how many were sent."""
        state = await self.api.get_state()
        cursor = int(state.get(K_PRICE_LAST_ID) or 0)
        channel = self.s.price_channel
        first_run = cursor == 0
        messages = await self.tg.messages(channel, min_id=cursor,
                                          limit=self.s.first_run_scan if first_run else 100)
        pdfs = [m for m in messages if m.is_pdf]
        if first_run:
            pdfs = pdfs[-1:]
        sent = 0
        for msg in pdfs:
            if not await self._send_pdf(channel, msg):
                return sent           # shopapi down: retry from here next time
            sent += 1
            cursor = max(cursor, msg.id)
            await self.api.put_state(K_PRICE_LAST_ID, str(cursor))
        newest = max((m.id for m in messages), default=cursor)
        if newest > cursor:
            await self.api.put_state(K_PRICE_LAST_ID, str(newest))
        return sent

    async def _send_pdf(self, channel: str, msg: TgMessage) -> bool:
        ref = f"t.me/{channel}/{msg.id}"
        if msg.file_size > self.s.pdf_max_bytes:
            log.warning("skipped %s: %d bytes is over the limit", ref, msg.file_size)
            return True
        data = await self.tg.download(msg, self.s.pdf_max_bytes)
        if not data.startswith(b"%PDF"):
            log.warning("skipped %s: not a PDF file", ref)
            return True
        posted = msg.date.isoformat() if msg.date else None
        try:
            result = await self.api.post_pricelist(data, source_ref=ref, posted_at=posted)
        except ApiError as exc:
            log.warning("price list %s not delivered: %s", ref, exc)
            return False
        log.info("price list %s -> %s %s", ref, result.get("outcome"),
                 "; ".join(result.get("reasons") or []))
        return True

    # ---- proxy channels -------------------------------------------------------------
    def collect_due(self, collected_at: str) -> bool:
        if not self.s.proxy_channels:
            return False
        try:
            last = datetime.fromisoformat(collected_at)
        except ValueError:
            return True
        return self._now() - last >= timedelta(days=self.s.proxy_collect_days)

    async def collect_tick(self, *, force: bool = False) -> int:
        """Proxy links from the followed channels -> shopapi candidates."""
        state = await self.api.get_state()
        if not force and not self.collect_due(state.get(K_COLLECTED_AT) or ""):
            return 0
        try:
            last_ids = json.loads(state.get(K_PROXY_LAST_IDS) or "{}")
            if not isinstance(last_ids, dict):
                last_ids = {}
        except ValueError:
            last_ids = {}
        added = 0
        for channel in self.s.proxy_channels:
            since = int(last_ids.get(channel) or 0)
            try:
                messages = await self.tg.messages(channel, min_id=since, limit=200)
            except Exception as exc:  # noqa: BLE001 - one bad channel must not stop the rest
                log.warning("proxy channel %s unreadable (%s)", channel, type(exc).__name__)
                continue
            links = extract_links([m.text for m in messages] + [u for m in messages for u in m.urls])
            for start in range(0, len(links), 500):
                result = await self.api.candidates(links[start:start + 500], f"channel:{channel}")
                added += int(result.get("added") or 0)
            if messages:
                last_ids[channel] = max(m.id for m in messages)
            log.info("proxy channel %s: %d links", channel, len(links))
        await self.api.put_json_state(K_PROXY_LAST_IDS, last_ids)
        await self.api.put_state(K_COLLECTED_AT, self._now().isoformat(timespec="seconds"))
        return added

    # ---- status / loop ----------------------------------------------------------------
    async def publish_status(self) -> None:
        link = self.tg.proxy
        status = {
            "connected": self.tg.connected,
            "proxy": _where(link) if self.tg.connected else "",
            "proxy_id": link.id if link else None,
            "login_required": self._login_missing,
            "error": self.last_error[:200],
            "at": self._now().isoformat(timespec="seconds"),
        }
        try:
            await self.api.put_json_state(K_STATUS, status)
        except ApiError as exc:
            log.debug("status not published: %s", exc)

    async def step(self) -> None:
        """Run whatever is due (called every few seconds)."""
        now = self._clock()
        if now >= self._next["health"]:
            self._next["health"] = now + self.s.health_interval_sec
            await self.health_tick()
            await self.publish_status()
        if not self.tg.connected:
            # Retry sooner than the health interval while down, but not in a tight loop.
            self._next["health"] = min(self._next["health"], now + 60)
            return
        for name, interval, job in (
            ("price", self.s.price_interval_sec, self.price_tick),
            ("collect", 6 * 3600, self.collect_tick),
            ("probe", self.s.probe_interval_sec, self.probe_tick),
        ):
            if now < self._next[name]:
                continue
            self._next[name] = now + interval
            try:
                await job()
            except ApiError as exc:
                log.warning("%s: %s", name, exc)
            except Exception as exc:  # noqa: BLE001 - FloodWait, network, ...
                log.warning("%s failed (%s)", name, type(exc).__name__)
                if name != "probe":
                    self._next["health"] = 0.0      # check the connection now

    async def run(self, stop: asyncio.Event) -> None:
        log.info("shoptg worker started (price channel @%s, %d proxy channels)",
                 self.s.price_channel, len(self.s.proxy_channels))
        try:
            while not stop.is_set():
                await self.step()
                try:
                    await asyncio.wait_for(stop.wait(), 5)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.tg.disconnect()
            log.info("shoptg worker stopped")
