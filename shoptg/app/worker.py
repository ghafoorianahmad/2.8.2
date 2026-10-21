"""The worker loop (REQUIREMENTS §5–6).

* price channel every ``TG_PRICE_INTERVAL_MIN`` (10): PDFs newer than the cursor
  go to ``/worker/pricelists`` (shopapi decides duplicate / older / held); the
  cursor moves past images and text posts too. First run: newest PDF only;
* proxy channels (default @ProxyMTProto) every ``TG_PROXY_COLLECT_HOURS`` (24),
  and hourly while fewer than ``TG_PROXY_POOL_SIZE`` (5) proxies work: links read
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
from tgproxy import ProxyLink, extract_links, from_pool, parse_proxy_link
from .shopapi import ApiError, WorkerApi
from . import webpreview

log = logging.getLogger(__name__)

K_PRICE_LAST_ID = "tg_price_last_id"
K_COLLECTED_AT = "tg_proxy_collected_at"
K_PROXY_LAST_IDS = "tg_proxy_last_ids"
K_STATUS = "tg_status"

#: Extra working proxies kept beyond TG_PROXY_POOL_SIZE (a failure must not empty it).
POOL_SPARE = 2
#: While fewer than pool_size proxies work, collect again after this long.
REFILL_AFTER = timedelta(hours=1)
#: How often the collection is considered (it decides itself whether it is due).
COLLECT_CHECK_SEC = 30 * 60
#: Consecutive download failures of a price-list PDF before the owner is alerted.
PRICE_FAIL_ALERT = 3
ALERT_PRICELIST = "telegram_pricelist_error"


def flood_seconds(exc: BaseException) -> int:
    """Seconds Telegram asked us to wait (FloodWait and friends), else 0."""
    if type(exc).__name__ in ("FloodWaitError", "FloodPremiumWaitError", "SlowModeWaitError",
                              "FloodTestPhoneWaitError"):
        try:
            return max(1, int(getattr(exc, "seconds", 60) or 60))
        except (TypeError, ValueError):
            return 60
    return 0


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
        self._paused_until = 0.0
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

    # ---- price channel ------------------------------------------------------------
    async def price_tick(self) -> int:
        """Send new PDFs to shopapi; returns how many were sent."""
        self.price_info["checked_at"] = self._now().isoformat(timespec="seconds")
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
        posted = msg.date.isoformat() if msg.date else None
        try:
            result = await self.api.post_pricelist(data, source_ref=ref, posted_at=posted)
        except ApiError as exc:
            log.warning("price list %s not delivered: %s", ref, exc)
            return False
        log.info("price list %s -> %s %s", ref, result.get("outcome"),
                 "; ".join(result.get("reasons") or []))
        self._price_result(ref, str(result.get("outcome") or ""))
        return True

    def _price_result(self, ref: str, outcome: str) -> None:
        self.price_info.update(ref=ref, outcome=outcome,
                               at=self._now().isoformat(timespec="seconds"))

    # ---- proxy channels -------------------------------------------------------------
    def collect_due(self, collected_at: str, healthy: int | None = None) -> bool:
        """Daily (TG_PROXY_COLLECT_HOURS), or hourly while the pool is short."""
        if not self.s.proxy_channels:
            return False
        try:
            last = datetime.fromisoformat(collected_at)
        except ValueError:
            return True
        elapsed = self._now() - last
        if elapsed >= timedelta(hours=self.s.proxy_collect_hours):
            return True
        return healthy is not None and healthy < self.s.pool_size and elapsed >= REFILL_AFTER

    async def healthy_count(self) -> int:
        """Usable proxies that worked at their last check."""
        try:
            pool = await self.api.proxies()
        except ApiError:
            return 0
        return sum(1 for p in pool if p.get("last_ok_at") and not p.get("failing_now"))

    async def _channel_links(self, channel: str, last_ids: dict) -> tuple[list[str], str]:
        """Proxy links of one channel, newest first: with the account when it is
        connected, else (or when that fails) from the public web preview."""
        if self.tg.connected:
            since = int(last_ids.get(channel) or 0)
            try:
                messages = await self.tg.messages(channel, min_id=since,
                                                  limit=200 if since else 100)
            except Exception as exc:  # noqa: BLE001 - one bad channel must not stop the rest
                if flood_seconds(exc):
                    raise
                log.warning("proxy channel %s unreadable (%s)", channel, type(exc).__name__)
            else:
                if messages:
                    last_ids[channel] = max(m.id for m in messages)
                newest = list(reversed(messages))
                return extract_links([m.text for m in newest] +
                                     [u for m in newest for u in m.urls]), "account"
        if self.s.web_preview:
            try:
                return await webpreview.fetch_links(channel), "web"
            except webpreview.PreviewError as exc:
                log.info("web preview of %s: %s", channel, exc)
        return [], ""

    async def collect_tick(self, *, force: bool = False) -> int:
        """New proxy links -> tested -> the working ones into the pool. Returns how
        many working proxies were added."""
        if not self.s.proxy_channels:
            return 0
        state = await self.api.get_state()
        healthy = await self.healthy_count()
        if not force and not self.collect_due(state.get(K_COLLECTED_AT) or "", healthy):
            return 0
        try:
            last_ids = json.loads(state.get(K_PROXY_LAST_IDS) or "{}")
            if not isinstance(last_ids, dict):
                last_ids = {}
        except ValueError:
            last_ids = {}
        found: list[tuple[str, str]] = []
        ways: list[str] = []
        for channel in self.s.proxy_channels:
            links, way = await self._channel_links(channel, last_ids)
            if way:
                ways.append(way)
            seen = {raw for raw, _ in found}
            found += [(raw, f"channel:{channel}") for raw in links if raw not in seen]
            log.info("proxy channel %s: %d links (%s)", channel, len(links), way or "unreadable")
        added, tested = await self._test_and_add(found, healthy)
        await self.api.put_json_state(K_PROXY_LAST_IDS, last_ids)
        await self.api.put_state(K_COLLECTED_AT, self._now().isoformat(timespec="seconds"))
        self.collect_info = {"at": self._now().isoformat(timespec="seconds"), "found": len(found),
                             "tested": tested, "added": added, "via": ",".join(ways)}
        if added and not self.tg.connected:
            self._next["health"] = 0.0          # a new proxy may get us connected now
        return added

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
        status = {
            "connected": self.tg.connected,
            "proxy": _where(link) if self.tg.connected else "",
            "proxy_id": link.id if link else None,
            "login_required": self._login_missing,
            "error": self.last_error[:200],
            "at": self._now().isoformat(timespec="seconds"),
            # v2.9.0 (no secrets: which key kind, the channel, counts and times)
            "api_preset": self.s.api_preset,
            "price_channel": self.s.price_channel,
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
            ("price", self.s.price_interval_sec, self.price_tick, True),
            # v2.9.0: also without a connection (web preview + anonymous tests)
            ("collect", COLLECT_CHECK_SEC, self.collect_tick, False),
            ("probe", self.s.probe_interval_sec, self.probe_tick, True),
        ):
            if now < self._next[name] or (needs_connection and not connected):
                continue
            self._next[name] = now + interval
            try:
                await job()
            except ApiError as exc:
                log.warning("%s: %s", name, exc)
            except Exception as exc:  # noqa: BLE001 - FloodWait, network, ...
                if self._flood(exc, now):
                    await self.publish_status()
                    break
                log.warning("%s failed (%s)", name, type(exc).__name__)
                if name != "probe":
                    self._next["health"] = 0.0      # check the connection now
            if name in ("price", "collect"):
                await self.publish_status()

    def _flood(self, exc: BaseException, now: float) -> bool:
        """A FloodWait: pause every job for as long as Telegram asks."""
        seconds = flood_seconds(exc)
        if not seconds:
            return False
        self._paused_until = now + seconds + 5
        self.last_error = f"Telegram asked to wait {seconds} s"
        log.warning("Telegram asked to wait %d s: every job paused", seconds)
        return True

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
